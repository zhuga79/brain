"""Контракт очереди задач — единственная реализация чтения и записи.

Один и тот же контракт был реализован независимо в четырёх местах: `brain-task`
(через четыре модуля с позиционным ABI), `brain-shell`, `runtime/mcp/tools_tasks`
и дашборд. Каждое изменение требовало четырёх согласованных правок, и на практике
они расходились — например, MCP дописывал `active.md` через `open("a")` без
блокировки очереди, пока `brain-task` уже писал через `brain_core.taskfile`.

Здесь чтение и запись живут вместе, потому что это один контракт: фильтры
`next`/`list` обязаны понимать ровно те блоки, которые пишет `add`.

Запись физически выполняет `brain_core.taskfile` — единственный владелец файлов
очереди. Этот модуль добавляет к ней смысл: генерацию идентификатора, сборку
блока, фильтры и разрешение зависимостей.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import brain_task_parser
import brain_tasks
from brain_core import atomic, clock, journal, paths, taskfile
from brain_core.model_signature import (
    AUDIT_OP,
    ModelSignatureError,
    ResolvedModel,
    resolve_completion_model,
    validate_model_signature,
)

STATE_BY_STATUS = {"open": " ", "in_progress": "~", "blocked": "!", "done": "x"}
DEPS_MARKERS = {" ": "○", "~": "◐", "x": "●", "!": "✗", "?": "?"}


# ── чтение ───────────────────────────────────────────────────────────────────

def _read(path: Path) -> str:
    """Текст файла очереди; отсутствие файла — пустая очередь, а не отказ.

    Проверка существования до чтения, а не перехват исключения: Brain без
    заведённой очереди — штатное состояние (новый workspace), а вот ошибка
    чтения существующего файла должна быть видна, а не превращаться в «задач нет».
    Битый UTF-8 не ошибка чтения: atomic.read_text подставляет U+FFFD, как
    дашборд и brain-shell до e46226f.
    """
    return atomic.read_text(path) if path.exists() else ""


def active_text(brain: Path | None = None) -> str:
    return _read(paths.active_file(brain))


def done_text(brain: Path | None = None) -> str:
    return _read(paths.done_file(brain))


def load_active(brain: Path | None = None) -> list[dict[str, Any]]:
    """Задачи очереди в нормализованной форме (priority, depends_on, surface).

    `surface` — effective_surface: явный surface: побеждает, иначе роль из
    INTERACTIVE_ROLES или gate: даёт interactive, иначе headless.
    Ключ `raw` сюда не входит: исходный блок — через find() / blocks().
    """
    return brain_tasks.parse_tasks(active_text(brain))


def load_done(brain: Path | None = None) -> list[dict[str, Any]]:
    """Задачи архива в той же нормализованной форме, что load_active."""
    return brain_tasks.parse_tasks(done_text(brain))


def blocks(brain: Path | None = None) -> list[dict[str, Any]]:
    """Разобранные блоки очереди в сыром виде парсера (prio, deps, raw)."""
    parsed = (brain_task_parser.parse_block(block) for block in brain_task_parser.find_blocks(active_text(brain)))
    return [info for info in parsed if info]


def role_matches(info: dict[str, Any], role: str) -> bool:
    """Фильтр по роли. Пустая роль в задаче означает developer — так документирован формат."""
    if not role:
        return True
    return info.get("role", "") == role or (role == "developer" and not info.get("role"))


def filter_tasks(
    items: Iterable[dict[str, Any]], *, role: str = "", mode: str = "", status: str = "open",
) -> list[dict[str, Any]]:
    target_state = STATE_BY_STATUS.get(status)
    out = []
    for info in items:
        if status != "all" and target_state and info.get("state") != target_state:
            continue
        if not role_matches(info, role):
            continue
        if mode and info.get("mode") != mode:
            continue
        out.append(info)
    return out


def find(task_id: str, brain: Path | None = None) -> tuple[dict[str, Any] | None, str]:
    """Задача по идентификатору — сначала в очереди, потом в архиве."""
    for text in (active_text(brain), done_text(brain)):
        if block := brain_task_parser.find_block(text, task_id):
            return brain_task_parser.parse_block(block), block
    return None, ""


def next_task(brain: Path | None = None, *, role: str = "", surface: str = "") -> dict[str, Any]:
    """Верхняя доступная задача и список заблокированных зависимостями.

    Возвращает `{"task": …|None, "blocked": [...]}` — заблокированные нужны
    вызывающему, чтобы объяснить, почему работы нет.
    """
    combined = active_text(brain) + "\n" + done_text(brain)
    available: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for info in blocks(brain):
        if info.get("state") != " " or not role_matches(info, role):
            continue
        info["surface"] = brain_task_parser.effective_surface(info)
        # headless-автозапуск не должен молча забирать интерактивную задачу
        if surface and info["surface"] != surface:
            continue
        info["blocked_by"] = [dep for dep in info.get("deps", []) if not brain_task_parser.is_done(combined, dep)]
        (blocked if info["blocked_by"] else available).append(info)
    return {"task": available[0] if available else None, "blocked": blocked}


def deps_tree(task_id: str, brain: Path | None = None, *, depth_limit: int = 10) -> dict[str, Any]:
    """Дерево зависимостей задачи. Цикл обрывается пометкой, а не рекурсией."""
    combined = active_text(brain) + "\n" + done_text(brain)
    seen: set[str] = set()

    def walk(tid: str, depth: int = 0) -> dict[str, Any]:
        if tid in seen or depth > depth_limit:
            return {"id": tid, "shown_above": True}
        seen.add(tid)
        block = brain_task_parser.find_block(combined, tid)
        if not block:
            return {"id": tid, "missing": True}
        info = brain_task_parser.parse_block(block) or {}
        return {
            "id": tid,
            "state": info.get("state", "?"),
            "title": info.get("title", ""),
            "deps": [walk(dep, depth + 1) for dep in info.get("deps", [])],
        }

    return walk(task_id)


# ── запись ───────────────────────────────────────────────────────────────────

# Кириллица в хвосте id, иначе заголовок без латиницы даёт пустой slug и
# запасной суффикс %H%M%S — t-YYYY-MM-DD-050654 вместо читаемого хвоста.
_CYRILLIC_SLUG = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g",
})


def slugify(text: str, limit: int = 30) -> str:
    mapped = text.lower().translate(_CYRILLIC_SLUG)
    return re.sub(r"[^a-z0-9]+", "-", mapped)[:limit].strip("-")


def new_task_id(title: str, brain: Path | None = None) -> str:
    """Свободный идентификатор вида t-ГГГГ-ММ-ДД-slug.

    Дата и запасной суффикс `%H%M%S` берутся из одного `clock.now()` — UTC.
    Это расходится с прежним bash `date +%Y-%m-%d` (локальный день): в UTC+3
    с полуночи до трёх id несёт вчерашнюю UTC-дату. UTC выбран сознательно —
    метки задач, журнала и имён файлов уже UTC.
    """
    moment = clock.now()
    slug = slugify(title) or moment.strftime("%H%M%S")
    base = f"t-{clock.utc_now(moment)[:10]}-{slug}"
    corpus = active_text(brain) + "\n" + done_text(brain)
    candidate, n = base, 2
    while re.search(rf"\b{re.escape(candidate)}\b", corpus):
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def render(
    task_id: str, title: str, *, role: str = "developer", mode: str = "solo", priority: str = "P2",
    council: list[str] | None = None, depends_on: list[str] | None = None, acceptance: str = "TODO",
) -> str:
    lines = [f"- [ ] [{priority}] {task_id} — {title}", f"      role: {role}   mode: {mode}"]
    if council:
        lines.append(f"      council: [{', '.join(council)}]")
    if depends_on:
        lines.append(f"      depends_on: [{', '.join(depends_on)}]")
    lines.append(f"      acceptance: {acceptance}")
    return "\n".join(lines)


def add(
    title: str, brain: Path | None = None, *, role: str = "developer", mode: str = "solo", priority: str = "P2",
    council: list[str] | None = None, depends_on: list[str] | None = None, acceptance: str = "TODO",
) -> str:
    """Добавить задачу в очередь. Возвращает выданный идентификатор."""
    active = paths.active_file(brain)
    with taskfile.queue_lock(active.parent):
        task_id = new_task_id(title, brain)
        block = render(
            task_id, title, role=role, mode=mode, priority=priority,
            council=council, depends_on=depends_on, acceptance=acceptance,
        )
        text = atomic.read_text(active)
        if text and not text.endswith("\n"):
            text += "\n"
        taskfile.atomic_write(active, text + "\n" + block + "\n")
    return task_id


def take(task_id: str, agent: str, brain: Path | None = None) -> None:
    if not str(agent).strip():
        raise ValueError("agent_id required")
    taskfile.take(paths.active_file(brain), task_id, agent)


def release(task_id: str, brain: Path | None = None, *, agent: str | None = None) -> None:
    if agent is not None and not str(agent).strip():
        raise ValueError("agent_id required")
    taskfile.release(paths.active_file(brain), task_id, agent)


def block(task_id: str, brain: Path | None = None, *, agent: str | None = None) -> None:
    if agent is not None and not str(agent).strip():
        raise ValueError("agent_id required")
    taskfile.block(paths.active_file(brain), task_id, agent)


def reconcile(brain: Path | None = None, *, fix: bool = False) -> list[dict[str, Any]]:
    """Расхождения «владелец задачи ≠ владелец лока»; с fix=True — их устранение."""
    return taskfile.reconcile_locks(paths.active_file(brain), fix=fix)


def complete(
    task_id: str,
    agent: str,
    model: str,
    brain: Path | None = None,
    *,
    allow_unsigned: bool = False,
) -> ResolvedModel:
    if not str(agent).strip():
        raise ValueError("agent_id required")
    resolved = resolve_completion_model(model, allow_unsigned=allow_unsigned)
    taskfile.complete(
        paths.active_file(brain), paths.done_file(brain), task_id, agent, resolved.value,
    )
    if resolved.unsigned:
        journal.append(AUDIT_OP, task_id, agent, resolved.audit_extra, brain)
    return resolved


# ── CLI: именованный интерфейс для bash-фасада ───────────────────────────────
#
# Прежний ABI был позиционным: `python3 -m brain_task_next <A> <D> <role>
# <json> <bin_dir> <surface> <client>`. Семь позиций без имён — добавление
# восьмой означало править каждого вызывающего, а перепутанный порядок
# проявлялся не ошибкой, а тихо неверной выборкой.

def print_next(args: argparse.Namespace) -> int:
    result = next_task(args.brain, role=args.role, surface=args.surface)
    task, blocked = result["task"], result["blocked"]
    if task:
        if args.json:
            print(json.dumps({"ok": True, "task": {
                "id": task["id"], "title": task["title"], "prio": task["prio"],
                "role": task.get("role", ""), "deps": task.get("deps", []), "blocked_by": [],
                "surface": task.get("surface", "headless"), "gate": task.get("gate", ""),
            }}))
        else:
            print(f"[{task['prio']}] {task['id']} — {task['title']}")
            if task.get("role"):
                print(f"  role: {task['role']}")
            if task.get("surface") == "interactive":
                gate = f" (gate: {task['gate']})" if task.get("gate") else ""
                print(f"  surface: interactive{gate} — launch in a visible window")
            if task.get("deps"):
                print(f"  deps satisfied: {task['deps']}")
    elif blocked:
        if args.json:
            print(json.dumps({"ok": False, "reason": "blocked", "blocked_tasks": [
                {"id": item["id"], "title": item["title"], "prio": item["prio"], "blocked_by": item["blocked_by"]}
                for item in blocked[:5]
            ]}))
        else:
            print("(no available — все open задачи заблокированы deps)")
            print()
            print("Заблокированные:")
            for item in blocked[:5]:
                print(f"  [{item['prio']}] {item['id']} — {item['title']}")
                print(f"    blocked by: {item['blocked_by']}")
    else:
        if args.json:
            print(json.dumps({"ok": False, "reason": "no_tasks", "role_filter": args.role or None}))
        else:
            print("(no open tasks)" + (f" for role {args.role}" if args.role else ""))
    return 0


def print_list(args: argparse.Namespace) -> int:
    tasks = filter_tasks(blocks(args.brain), role=args.role, mode=args.mode)
    if args.json:
        print(json.dumps({"ok": True, "tasks": tasks}, ensure_ascii=False, indent=2))
        return 0
    for task in tasks:
        role, mode = task.get("role", ""), task.get("mode", "")
        print(f"- [ ] [{task['prio']}] {task['id']} — {task['title']}")
        if role or mode:
            print(f"      {'role: ' + role if role else ''}   {'mode: ' + mode if mode else ''}".strip())
    return 0


def print_show(args: argparse.Namespace) -> int:
    info, raw = find(args.task_id, args.brain)
    if not info:
        if args.json:
            print(json.dumps({"ok": False, "error": f"task {args.task_id} not found"}))
        else:
            print(f"task {args.task_id} not found", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True, "task": info}, ensure_ascii=False, indent=2))
    else:
        print(raw)
    return 0


def print_deps(args: argparse.Namespace) -> int:
    def walk(node: dict[str, Any], depth: int = 0) -> None:
        pad = "  " * depth
        if node.get("missing"):
            print(pad + "? ?  (not found)")
            return
        if node.get("shown_above"):
            print(pad + f"... {node['id']} (already shown)")
            return
        marker = DEPS_MARKERS.get(node.get("state", "?"), "?")
        print(pad + f"{marker} {node['id']}  {node.get('title', '')[:60]}")
        for child in node.get("deps", []):
            walk(child, depth + 1)

    walk(deps_tree(args.task_id, args.brain))
    return 0


def print_complete(args: argparse.Namespace) -> int:
    try:
        resolved = complete(
            args.task_id, args.agent, args.model, args.brain,
            allow_unsigned=args.allow_unsigned,
        )
    except (ModelSignatureError, ValueError, taskfile.TaskError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(resolved.value)
    return 0


def print_add(args: argparse.Namespace) -> int:
    task_id = add(
        args.title, args.brain, role=args.role, mode=args.mode, priority=args.prio,
        council=args.council or None, depends_on=args.depends_on or None, acceptance=args.acceptance,
    )
    print(task_id)
    return 0


def print_reconcile(args: argparse.Namespace) -> int:
    findings = reconcile(args.brain, fix=args.fix)
    if args.json:
        print(json.dumps({"ok": True, "fixed": bool(args.fix), "findings": findings}, ensure_ascii=False, indent=2))
        return 0 if (args.fix or not findings) else 1
    if not findings:
        print("очередь и локи согласованы")
        return 0
    for item in findings:
        line = f"{item['id']}  {item['kind']}  task={item['task_owner'] or '—'}  lock={item['lock_owner'] or '—'}"
        if item.get("action"):
            line += f"  → {item['action']}"
        print(line)
    if not args.fix:
        print()
        print("исправить: brain-task reconcile --fix")
        return 1
    return 0


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brain_app.queue", description="Очередь задач Brain.")
    parser.add_argument("--brain", default=None, help="Путь к Brain. По умолчанию $BRAIN_PATH или ~/brain.")
    sub = parser.add_subparsers(dest="command", required=True)

    nxt = sub.add_parser("next", help="верхняя доступная задача")
    nxt.add_argument("--role", default="")
    nxt.add_argument("--surface", default="", choices=["", "headless", "interactive"])
    nxt.add_argument("--json", action="store_true")
    nxt.set_defaults(func=print_next)

    lst = sub.add_parser("list", help="открытые задачи с фильтрами")
    lst.add_argument("--role", default="")
    lst.add_argument("--mode", default="")
    lst.add_argument("--json", action="store_true")
    lst.set_defaults(func=print_list)

    show = sub.add_parser("show", help="одна задача целиком")
    show.add_argument("task_id")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=print_show)

    deps = sub.add_parser("deps", help="дерево зависимостей задачи")
    deps.add_argument("task_id")
    deps.set_defaults(func=print_deps)

    new = sub.add_parser("add", help="добавить задачу; печатает выданный id")
    new.add_argument("title")
    new.add_argument("--role", default="developer")
    new.add_argument("--mode", default="solo")
    new.add_argument("--prio", default="P2")
    new.add_argument("--acceptance", default="TODO")
    new.add_argument("--council", default="", type=_csv, help="роли через запятую")
    new.add_argument("--depends-on", dest="depends_on", default="", type=_csv, help="id через запятую")
    new.set_defaults(func=print_add)

    done = sub.add_parser("complete", help="закрыть задачу с подписью модели")
    done.add_argument("task_id")
    done.add_argument("--as", dest="agent", required=True)
    done.add_argument("--model", default="", help="versioned provider-model-version")
    done.add_argument(
        "--allow-unsigned", action="store_true",
        help="legacy hatch: record model: unsigned and audit it",
    )
    done.set_defaults(func=print_complete)

    fixup = sub.add_parser("reconcile", help="расхождения между `by:` задачи и владельцем лока")
    fixup.add_argument("--fix", action="store_true", help="устранить расхождения")
    fixup.add_argument("--json", action="store_true")
    fixup.set_defaults(func=print_reconcile)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.brain = paths.brain_path(args.brain)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
