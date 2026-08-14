"""Единственный владелец записи в tasks/active.md и tasks/done.md.

Раньше очередь правили четыре независимых места: инлайн-heredoc'и в brain-task,
mcp/tools_tasks.add_task и brain_federation/plan.py — все через open(path, "w")
без блокировки. Протокол локов защищает *задачу*, а не *файл*: два агента,
работающие над разными задачами, читали очередь, меняли свою строку и
записывали файл целиком, затирая правку соседа.

Здесь запись идёт под межпроцессной блокировкой и атомарно:

    flock(отдельный lock-файл) → читаем → меняем → tmp+fsync+os.replace

Блокируется отдельный файл, а не сам active.md: flock живёт на inode, а
os.replace подставляет новый inode, так что блокировка на самом active.md
терялась бы ровно в момент записи.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from brain_core import atomic, grammar
from brain_core.clock import utc_now  # noqa: F401  (переэкспорт для совместимости)

LOCK_NAME = ".taskfile.lock"
COMPLETE_JOURNAL_DIR = ".taskfile-complete"


def queue_lock(tasks_dir: Path):
    """Блокировка на всё время операции над очередью.

    Одна блокировка на каталог задач, а не на файл: complete переносит задачу
    из active.md в done.md, и оба файла должны меняться как одно целое.
    """
    return atomic.file_lock(tasks_dir / LOCK_NAME)


def atomic_write(path: Path, text: str) -> None:
    """Записать файл целиком без промежуточного состояния на диске."""
    atomic.write_text(path, text, prefix=".taskfile.")


def _read(path: Path) -> str:
    return atomic.read_text(path)


def _lock_owner_path(active: Path, tid: str) -> Path:
    return active.parent.parent / ".locks" / tid / "owner"


def _parse_lock_owner(raw: str) -> tuple[str, int, int]:
    parts = raw.strip().split("|")
    if len(parts) != 3:
        raise TaskError("invalid lock owner format")
    owner, started, ttl = parts
    try:
        return owner, int(started), int(ttl)
    except ValueError as exc:
        raise TaskError("invalid lock owner format") from exc


def _extract_owner(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("by:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _ensure_in_progress_owner(active: Path, tid: str, body: str, agent: str | None) -> None:
    owner = _extract_owner(body)
    if not owner:
        raise TaskError(f"task owner missing: {tid}")
    if not agent:
        raise TaskError(f"task owner required: {tid}")
    if owner != agent:
        raise TaskError(f"task owned by {owner}, not {agent}")

    owner_file = _lock_owner_path(active, tid)
    if not owner_file.is_file():
        # Исторические прямые вызовы brain_app.queue.take/complete не создают
        # lock-файл. Там всё ещё есть смысл сверить `by:` до записи, а строгую
        # проверку owner/stale выполнять только когда lock реально присутствует.
        return
    lock_owner, started, ttl = _parse_lock_owner(_read(owner_file))
    if lock_owner != agent:
        raise TaskError(f"lock owned by {lock_owner}, not {agent}")
    if int(time.time()) - started > ttl:
        raise TaskError(f"task lock is stale: {tid}")


def _pattern(tid: str, state: str) -> re.Pattern:
    """Заголовок задачи в заданных состояниях — форма берётся из общей грамматики."""
    return grammar.head_re_for(tid, state)


class TaskError(RuntimeError):
    """Операция невозможна: задачи нет или она в неподходящем состоянии."""


def complete_journal_path(tasks_dir: Path, tid: str) -> Path:
    """Локальный recovery-файл для конкретного complete-перехода."""
    return tasks_dir / COMPLETE_JOURNAL_DIR / f"{tid}.json"


def cleanup_complete_journal(path: Path) -> None:
    """Удалить recovery-файл после успешной сходимости."""
    path.unlink(missing_ok=True)


def _any_state_pattern(tid: str) -> re.Pattern:
    return _pattern(tid, "[ !~x]")


def _done_count(text: str, tid: str) -> int:
    return len(_pattern(tid, "x").findall(text))


def _load_complete_journal(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskError(f"invalid completion journal: {path}") from exc
    required = {"task_id", "agent", "model", "completed", "entry"}
    if not isinstance(payload, dict) or any(not isinstance(payload.get(key), str) for key in required):
        raise TaskError(f"invalid completion journal: {path}")
    if payload["task_id"] not in path.name:
        raise TaskError(f"invalid completion journal: {path}")
    return payload


def _prepend_done_entry(done_text: str, entry: str) -> str:
    parts = done_text.split("\n", 3)
    head = "\n".join(parts[:2]) if len(parts) >= 2 else done_text.rstrip("\n")
    rest = parts[3] if len(parts) > 3 else ""
    return head + "\n\n" + entry + "\n" + rest


def _remove_active_task(active_text: str, tid: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", _any_state_pattern(tid).sub("", active_text, count=1))


def _recover_complete(active: Path, done: Path, tid: str) -> None:
    journal_path = complete_journal_path(active.parent, tid)
    payload = _load_complete_journal(journal_path)
    if not payload:
        return

    active_text = _read(active)
    done_text = _read(done)
    active_match = _any_state_pattern(tid).search(active_text)
    done_hits = _done_count(done_text, tid)
    if done_hits > 1:
        raise TaskError(f"completion journal inconsistent: duplicate done entries for {tid}")
    if not active_match and done_hits == 0:
        raise TaskError(f"completion journal inconsistent: {tid} missing in active.md and done.md")

    if done_hits == 0:
        atomic_write(done, _prepend_done_entry(done_text, payload["entry"]))
        done_text = _read(done)
    if active_match:
        atomic_write(active, _remove_active_task(active_text, tid))
    cleanup_complete_journal(journal_path)


def add(active: Path, entry: str) -> None:
    """Дописать готовый блок задачи в конец очереди."""
    with queue_lock(active.parent):
        txt = _read(active)
        if txt and not txt.endswith("\n"):
            txt += "\n"
        atomic_write(active, txt + entry)


def take(active: Path, tid: str, agent: str) -> None:
    """Перевести задачу в работу: [ ] → [~], дописать started/by."""
    with queue_lock(active.parent):
        txt = _read(active)
        pat = _pattern(tid, " ")
        if not pat.search(txt):
            # Повторный take тем же агентом — не ошибка, а отсутствие работы.
            # Сценарий из MEMORY.md (сначала brain-lock acquire, затем
            # brain-task take) и просто повторный запуск после обрыва связи
            # иначе упирались бы в отказ на задаче, которую агент уже держит.
            in_progress = _pattern(tid, "~").search(txt)
            if in_progress and f"by: {agent}" in in_progress.group(3):
                return
            raise TaskError(f"task not found or not open: {tid}")
        ts = utc_now()

        def repl(m: re.Match) -> str:
            return (
                m.group(1) + "~]" + m.group(2) + m.group(3)
                + f"      started: {ts}\n      by: {agent}\n"
            )

        atomic_write(active, pat.sub(repl, txt, count=1))


def release(active: Path, tid: str, agent: str | None = None) -> None:
    """Вернуть задачу в очередь: [~] → [ ], снять started/by."""
    with queue_lock(active.parent):
        txt = _read(active)
        pat = _pattern(tid, "~")
        match = pat.search(txt)
        if not match:
            # Задача уже в очереди — значит, освобождать нечего. Повторный
            # release не должен падать: агент, потерявший связь, повторяет
            # команду, и отказ здесь выглядел бы как невозможность отпустить
            # задачу.
            if _pattern(tid, " ").search(txt):
                return
            raise TaskError(f"task not in progress: {tid}")
        _ensure_in_progress_owner(active, tid, match.group(3), agent)

        def repl(m: re.Match) -> str:
            body = "".join(
                line for line in m.group(3).splitlines(keepends=True)
                if not line.lstrip().startswith(("started:", "by:"))
            )
            return m.group(1) + " ]" + m.group(2) + body

        atomic_write(active, pat.sub(repl, txt, count=1))


def block(active: Path, tid: str, agent: str | None = None) -> None:
    """Пометить задачу заблокированной: [ ]/[~] → [!].

    Причина в файл не пишется — она уходит в журнал и в сообщение коммита.
    Так было и до выделения модуля; менять формат блока задачи здесь незачем.
    """
    with queue_lock(active.parent):
        txt = _read(active)
        pat = _pattern(tid, "[ ~]")
        match = pat.search(txt)
        if not match:
            raise TaskError(f"task not found or not open/in-progress: {tid}")
        head = grammar.parse_head(match.group(0).splitlines()[0])
        if head and head.state == "~":
            _ensure_in_progress_owner(active, tid, match.group(3), agent)

        def repl(m: re.Match) -> str:
            return m.group(1) + "!]" + m.group(2) + m.group(3)

        atomic_write(active, pat.sub(repl, txt, count=1))


def complete(active: Path, done: Path, tid: str, agent: str, model: str) -> None:
    """Перенести задачу в done.md с подписью модели.

    Оба файла меняются под одной блокировкой: иначе задача может исчезнуть из
    active.md, не появившись в done.md.
    """
    with queue_lock(active.parent):
        _recover_complete(active, done, tid)
        txt = _read(active)
        pat = _pattern(tid, "[ ~]")
        m = pat.search(txt)
        if not m:
            if _done_count(_read(done), tid) == 1:
                return
            raise TaskError(f"task not found: {tid}")
        head = grammar.parse_head(m.group(0).splitlines()[0])
        if head and head.state == "~":
            _ensure_in_progress_owner(active, tid, m.group(3), agent)

        ts = utc_now()
        machine = "".join(
            line for line in m.group(3).splitlines(keepends=True)
            if not re.match(r"\s+(by|model|completed):", line)
        )
        entry = (
            "- [x]" + m.group(2) + machine
            + f"      by: {agent}\n      model: {model}\n      completed: {ts}\n"
        )

        journal_path = complete_journal_path(active.parent, tid)
        atomic.write_json(
            journal_path,
            {"task_id": tid, "agent": agent, "model": model, "completed": ts, "entry": entry},
        )
        dtxt = _read(done)
        if _done_count(dtxt, tid) == 0:
            atomic_write(done, _prepend_done_entry(dtxt, entry))
        atomic_write(active, _remove_active_task(txt, tid))
        cleanup_complete_journal(journal_path)


def _main(argv: list[str]) -> int:
    """CLI для brain-task: python3 -m brain_core.taskfile <op> ..."""
    import sys

    if not argv:
        print("usage: taskfile <add|take|release|block|complete> ...", file=sys.stderr)
        return 2

    op, rest = argv[0], argv[1:]
    try:
        if op == "add":
            add(Path(rest[0]), rest[1])
        elif op == "take":
            take(Path(rest[0]), rest[1], rest[2])
        elif op == "release":
            release(Path(rest[0]), rest[1], rest[2] if len(rest) > 2 else None)
        elif op == "block":
            block(Path(rest[0]), rest[1], rest[2] if len(rest) > 2 else None)
        elif op == "complete":
            complete(Path(rest[0]), Path(rest[1]), rest[2], rest[3], rest[4])
        else:
            print(f"unknown op: {op}", file=sys.stderr)
            return 2
    except TaskError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except IndexError:
        print(f"not enough arguments for {op}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_main(sys.argv[1:]))
