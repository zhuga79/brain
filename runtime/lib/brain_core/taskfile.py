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

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

from brain_core import atomic, grammar
from brain_core.clock import utc_now  # noqa: F401  (переэкспорт для совместимости)

LOCK_NAME = ".taskfile.lock"
COMPLETE_JOURNAL_DIR = ".taskfile-complete"
COMPLETE_JOURNAL_VERSION = "2"
TASK_ID_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
LOCK_TTL_DEFAULT = 600


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


def _locks_root(active: Path) -> Path:
    return active.parent.parent / ".locks"


def _lock_dir(active: Path, tid: str) -> Path:
    return _locks_root(active) / tid


def _lock_owner_path(active: Path, tid: str) -> Path:
    return _lock_dir(active, tid) / "owner"


def _write_lock_owner(path: Path, agent: str, ttl: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{agent}|{int(time.time())}|{int(ttl)}\n", encoding="utf-8")


def claim_lock(active: Path, tid: str, agent: str, ttl: int = LOCK_TTL_DEFAULT) -> bool:
    """Захватить лок задачи под тем же agent-id, что попадёт в `by:`.

    Формат owner-файла тот же, что у brain-lock (`agent|epoch|ttl`), и каталог
    создаётся тем же atomically-mkdir. Смысл в том, что перевод `[ ]`→`[~]`
    теперь не может состояться без лока: раньше запись состояния и захват лока
    были двумя независимыми шагами, и очередь оказывалась в состоянии, где
    владелец задачи и владелец лока — разные агенты.

    Возвращает True, если лок был создан этим вызовом (нужно для отката).
    """
    if not str(agent).strip():
        raise TaskError("agent id required")
    directory = _lock_dir(active, tid)
    directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        directory.mkdir()
    except FileExistsError:
        pass
    else:
        _write_lock_owner(directory / "owner", agent, ttl)
        return True

    owner_file = directory / "owner"
    if not owner_file.is_file():
        # Каталог без owner-файла — обрывок предыдущего запуска, не лок.
        _write_lock_owner(owner_file, agent, ttl)
        return True
    try:
        lock_owner, started, current_ttl = _parse_lock_owner(_read(owner_file))
    except TaskError:
        _write_lock_owner(owner_file, agent, ttl)
        return True
    if lock_owner == agent:
        _write_lock_owner(owner_file, agent, ttl)  # продление своего лока
        return False
    if int(time.time()) - started > current_ttl:
        _write_lock_owner(owner_file, agent, ttl)  # перехват протухшего
        return False
    raise TaskError(f"task locked by {lock_owner}, not {agent}: {tid}")


def _drop_lock(active: Path, tid: str) -> None:
    shutil.rmtree(_lock_dir(active, tid), ignore_errors=True)


def _validate_task_id(tid: str) -> str:
    if not TASK_ID_SAFE_RE.fullmatch(tid):
        raise TaskError(f"invalid task id: {tid}")
    return tid


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


def _ensure_lock_owner(active: Path, tid: str, agent: str) -> None:
    owner_file = _lock_owner_path(active, tid)
    if not owner_file.is_file():
        raise TaskError(f"task lock missing: {tid}")
    lock_owner, started, ttl = _parse_lock_owner(_read(owner_file))
    if lock_owner != agent:
        raise TaskError(f"lock owned by {lock_owner}, not {agent}")
    if int(time.time()) - started > ttl:
        raise TaskError(f"task lock is stale: {tid}")


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
    _ensure_lock_owner(active, tid, agent)


def _pattern(tid: str, state: str) -> re.Pattern:
    """Заголовок задачи в заданных состояниях — форма берётся из общей грамматики."""
    return grammar.head_re_for(tid, state)


class TaskError(RuntimeError):
    """Операция невозможна: задачи нет или она в неподходящем состоянии."""


def complete_journal_path(tasks_dir: Path, tid: str) -> Path:
    """Локальный recovery-файл для конкретного complete-перехода."""
    return tasks_dir / COMPLETE_JOURNAL_DIR / f"{_validate_task_id(tid)}.json"


def cleanup_complete_journal(path: Path) -> None:
    """Удалить recovery-файл после успешной сходимости."""
    path.unlink(missing_ok=True)


def _any_state_pattern(tid: str) -> re.Pattern:
    return _pattern(tid, "[ !~x]")


def _done_count(text: str, tid: str) -> int:
    return len(_pattern(tid, "x").findall(text))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _done_block_pattern(tid: str) -> re.Pattern:
    return grammar.block_re_for(tid, "x")


def _build_done_entry(task_block: str, agent: str, model: str, completed: str) -> str:
    lines = task_block.splitlines(keepends=True)
    if not lines:
        raise TaskError("invalid completion journal source block")
    head = grammar.parse_head(lines[0].rstrip("\n"))
    if not head:
        raise TaskError("invalid completion journal source block")
    body = "".join(lines[1:])
    machine = "".join(
        line for line in body.splitlines(keepends=True)
        if not re.match(r"\s+(by|model|completed):", line)
    )
    return (
        grammar.format_head(head._replace(state="x")) + "\n"
        + machine
        + f"      by: {agent}\n      model: {model}\n      completed: {completed}\n"
    )


def _active_block_fingerprint(task_block: str) -> str:
    return _sha256_text(task_block)


def _entry_fingerprint(entry: str) -> str:
    return _sha256_text(entry.rstrip("\n"))


def _load_complete_journal(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskError(f"invalid completion journal: {path}") from exc
    required = {
        "version",
        "task_id",
        "owner",
        "model",
        "model_signature",
        "completed",
        "source_active",
        "source_active_fingerprint",
        "final_entry_fingerprint",
    }
    if not isinstance(payload, dict) or any(not isinstance(payload.get(key), str) for key in required):
        raise TaskError(f"invalid completion journal: {path}")
    if payload["version"] != COMPLETE_JOURNAL_VERSION:
        raise TaskError(f"invalid completion journal: {path}")
    if payload["task_id"] != path.stem:
        raise TaskError(f"invalid completion journal: {path}")
    _validate_task_id(payload["task_id"])
    return payload


def _prepend_done_entry(done_text: str, entry: str) -> str:
    parts = done_text.split("\n", 3)
    head = "\n".join(parts[:2]) if len(parts) >= 2 else done_text.rstrip("\n")
    rest = parts[3] if len(parts) > 3 else ""
    return head + "\n\n" + entry + "\n" + rest


def _remove_active_task(active_text: str, tid: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", _any_state_pattern(tid).sub("", active_text, count=1))


def _validate_recovery_payload(
    active: Path,
    tid: str,
    agent: str,
    model: str,
    payload: dict[str, str],
    active_match: re.Match[str] | None,
    done_match: re.Match[str] | None,
) -> str:
    if payload["task_id"] != tid:
        raise TaskError(f"invalid completion journal: {complete_journal_path(active.parent, tid)}")
    if payload["owner"] != agent:
        raise TaskError(f"completion journal owner mismatch: {tid}")
    if payload["model"] != model:
        raise TaskError(f"completion journal model mismatch: {tid}")
    if payload["model_signature"] != _sha256_text(model):
        raise TaskError(f"invalid completion journal: {complete_journal_path(active.parent, tid)}")
    if payload["source_active_fingerprint"] != _active_block_fingerprint(payload["source_active"]):
        raise TaskError(f"invalid completion journal: {complete_journal_path(active.parent, tid)}")
    expected_entry = _build_done_entry(
        payload["source_active"], payload["owner"], payload["model"], payload["completed"],
    )
    if payload["final_entry_fingerprint"] != _entry_fingerprint(expected_entry):
        raise TaskError(f"invalid completion journal: {complete_journal_path(active.parent, tid)}")

    if active_match:
        active_block = active_match.group(0)
        head = grammar.parse_head(active_block.splitlines()[0])
        if head and head.state == "~":
            _ensure_in_progress_owner(active, tid, active_match.group(3), agent)
        elif head and head.state == " ":
            if _lock_owner_path(active, tid).exists():
                raise TaskError(f"task lock missing owner/body match: {tid}")
        if _active_block_fingerprint(active_block) != payload["source_active_fingerprint"]:
            raise TaskError(f"completion journal fingerprint mismatch: {tid}")
    else:
        if not done_match:
            _ensure_lock_owner(active, tid, agent)

    if done_match and _entry_fingerprint(done_match.group(1)) != payload["final_entry_fingerprint"]:
        raise TaskError(f"completion journal entry mismatch: {tid}")
    return expected_entry


def _recover_complete(active: Path, done: Path, tid: str, agent: str, model: str) -> None:
    journal_path = complete_journal_path(active.parent, tid)
    payload = _load_complete_journal(journal_path)
    if not payload:
        return

    active_text = _read(active)
    done_text = _read(done)
    active_match = _any_state_pattern(tid).search(active_text)
    done_match = _done_block_pattern(tid).search(done_text)
    done_hits = _done_count(done_text, tid)
    if done_hits > 1:
        raise TaskError(f"completion journal inconsistent: duplicate done entries for {tid}")
    if not active_match and done_hits == 0:
        raise TaskError(f"completion journal inconsistent: {tid} missing in active.md and done.md")
    expected_entry = _validate_recovery_payload(active, tid, agent, model, payload, active_match, done_match)

    if done_hits == 0:
        atomic_write(done, _prepend_done_entry(done_text, expected_entry))
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


def take(active: Path, tid: str, agent: str, *, ttl: int = LOCK_TTL_DEFAULT) -> None:
    """Перевести задачу в работу: [ ] → [~], дописать started/by.

    Лок захватывается здесь же, тем же agent-id, что уходит в `by:`. Раньше
    захват был отдельным шагом вызывающего (brain-task делал его, MCP делал,
    а прямой вызов brain_app.queue.take — нет), поэтому существовал путь, на
    котором задача уходила в работу вообще без лока.
    """
    _validate_task_id(tid)
    if not str(agent).strip():
        raise TaskError("agent id required")
    with queue_lock(active.parent):
        txt = _read(active)
        pat = _pattern(tid, " ")
        if not pat.search(txt):
            # Повторный take тем же агентом — не ошибка, а отсутствие работы.
            # Сценарий из MEMORY.md (сначала brain-lock acquire, затем
            # brain-task take) и просто повторный запуск после обрыва связи
            # иначе упирались бы в отказ на задаче, которую агент уже держит.
            in_progress = _pattern(tid, "~").search(txt)
            if in_progress and _extract_owner(in_progress.group(3)) == agent:
                claim_lock(active, tid, agent, ttl)
                return
            raise TaskError(f"task not found or not open: {tid}")
        created = claim_lock(active, tid, agent, ttl)
        ts = utc_now()

        def repl(m: re.Match) -> str:
            return (
                m.group(1) + "~]" + m.group(2) + m.group(3)
                + f"      started: {ts}\n      by: {agent}\n"
            )

        try:
            atomic_write(active, pat.sub(repl, txt, count=1))
        except BaseException:
            # Лок без записи в очереди — тот же рассинхрон, только зеркальный.
            if created:
                _drop_lock(active, tid)
            raise


def _released_text(txt: str, tid: str) -> str:
    """Текст очереди с задачей, возвращённой в open: [~] → [ ] без started/by."""
    def repl(m: re.Match) -> str:
        body = "".join(
            line for line in m.group(3).splitlines(keepends=True)
            if not line.lstrip().startswith(("started:", "by:"))
        )
        return m.group(1) + " ]" + m.group(2) + body

    return _pattern(tid, "~").sub(repl, txt, count=1)


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
        atomic_write(active, _released_text(txt, tid))


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


def _in_progress_owners(txt: str) -> dict[str, str]:
    """id задачи в работе → значение её `by:` (пустая строка, если поля нет)."""
    out: dict[str, str] = {}
    for match in grammar.BLOCK_RE.finditer(txt):
        block = match.group(1)
        head = grammar.parse_head(block.splitlines()[0])
        if not head or head.state != "~":
            continue
        out[head.task_id] = _extract_owner("\n".join(block.splitlines()[1:]))
    return out


def _lock_state(active: Path, tid: str) -> tuple[str, bool] | None:
    """(владелец лока, протух ли). None — лока нет или он нечитаем."""
    owner_file = _lock_owner_path(active, tid)
    if not owner_file.is_file():
        return None
    try:
        owner, started, ttl = _parse_lock_owner(_read(owner_file))
    except TaskError:
        return ("", True)
    return (owner, int(time.time()) - started > ttl)


def reconcile_locks(active: Path, *, fix: bool = False) -> list[dict[str, object]]:
    """Свести владельца задачи и владельца лока к одному агенту.

    Инцидент t-2026-08-14: `by:` называл одного агента, лок принадлежал
    другому, и `brain-task release` отвергался обеими сторонами — задачу не мог
    отпустить ни владелец лока, ни владелец задачи. Разбор такого расхождения
    должен быть штатной командой, а не ручным `rm -rf .locks/<id>`.

    Виды расхождений:

    * `owner_mismatch` — `[~] by: A`, лок принадлежит B;
    * `lock_missing`   — `[~] by: A`, лока нет;
    * `owner_missing`  — `[~]` вообще без `by:`;
    * `lock_stale`     — `[~] by: A`, лок A протух;
    * `orphan_lock`    — лок есть, задача не в работе.

    С `fix=True` расхождение устраняется: задача возвращается в `[ ]`, а лок
    снимается — кроме `lock_missing`, где лок восстанавливается на владельца
    задачи, потому что работа, скорее всего, идёт.
    """
    findings: list[dict[str, object]] = []
    queue_changed = False
    with queue_lock(active.parent):
        txt = _read(active)
        owners = _in_progress_owners(txt)

        locked_ids: set[str] = set()
        root = _locks_root(active)
        if root.is_dir():
            for entry in sorted(root.iterdir()):
                if entry.name.startswith(".") or entry.is_symlink() or not entry.is_dir():
                    continue
                locked_ids.add(entry.name)

        for tid in sorted(set(owners) | locked_ids):
            task_owner = owners.get(tid)
            lock = _lock_state(active, tid) if tid in locked_ids else None
            lock_owner = lock[0] if lock else ""
            stale = bool(lock and lock[1])

            if task_owner is None:
                kind = "orphan_lock"
            elif lock is None:
                kind = "lock_missing"
            elif not task_owner:
                kind = "owner_missing"
            elif lock_owner != task_owner:
                kind = "owner_mismatch"
            elif stale:
                kind = "lock_stale"
            else:
                continue

            finding: dict[str, object] = {
                "id": tid,
                "kind": kind,
                "task_owner": task_owner or "",
                "lock_owner": lock_owner,
                "stale": stale,
                "fixed": False,
            }
            if fix:
                if kind == "lock_missing":
                    claim_lock(active, tid, str(task_owner))
                    finding["action"] = f"lock restored for {task_owner}"
                else:
                    _drop_lock(active, tid)
                    if task_owner is not None:
                        txt = _released_text(txt, tid)
                        queue_changed = True
                        finding["action"] = "lock dropped, task returned to open"
                    else:
                        finding["action"] = "orphan lock dropped"
                finding["fixed"] = True
            findings.append(finding)

        if queue_changed:
            atomic_write(active, txt)
    return findings


def complete(active: Path, done: Path, tid: str, agent: str, model: str) -> None:
    """Перенести задачу в done.md с подписью модели.

    Оба файла меняются под одной блокировкой: иначе задача может исчезнуть из
    active.md, не появившись в done.md.
    """
    _validate_task_id(tid)
    with queue_lock(active.parent):
        _recover_complete(active, done, tid, agent, model)
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
        source_block = m.group(0)
        entry = _build_done_entry(source_block, agent, model, ts)

        journal_path = complete_journal_path(active.parent, tid)
        atomic.write_json(
            journal_path,
            {
                "version": COMPLETE_JOURNAL_VERSION,
                "task_id": tid,
                "owner": agent,
                "model": model,
                "model_signature": _sha256_text(model),
                "completed": ts,
                "source_active": source_block,
                "source_active_fingerprint": _active_block_fingerprint(source_block),
                "final_entry_fingerprint": _entry_fingerprint(entry),
            },
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
