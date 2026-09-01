import re
import os
import time
import shutil
from common import mcp, BRAIN, ACTIVE, DONE, LOCKS, append_log, git_commit, ts, find_task_block, parse_block
import brain_task_parser
from brain_app import queue
from brain_core.taskfile import LOCK_TTL_DEFAULT
from brain_core import autosave as _autosave
from brain_core.model_signature import ModelSignatureError, resolve_completion_model
from result import ok, error

_LOCK_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _require_lock_id(task_id: str) -> str | None:
    cleaned = str(task_id or "").strip()
    if not cleaned or not _LOCK_ID_RE.fullmatch(cleaned):
        return None
    return cleaned


def _require_agent_id(agent_id: str) -> str | None:
    cleaned = str(agent_id or "").strip()
    if not cleaned or not _LOCK_ID_RE.fullmatch(cleaned):
        return None
    return cleaned


def _require_force_reason(reason: str) -> str | None:
    cleaned = str(reason or "").strip()
    if not cleaned:
        return None
    return cleaned


def _read_lock_owner(owner_file) -> tuple[str | None, str | None]:
    if not owner_file.exists():
        return None, "corrupt lock"
    parts = owner_file.read_text().strip().split("|")
    if len(parts) < 3:
        return None, "corrupt owner"
    owner = _require_agent_id(parts[0])
    if not owner:
        return None, "corrupt owner"
    try:
        int(parts[1])
        int(parts[2])
    except ValueError:
        return None, "corrupt owner"
    return owner, None


@mcp.tool()
def acquire_lock(task_id: str, agent_id: str, ttl: int = LOCK_TTL_DEFAULT) -> dict:
    """Acquire a lock on a task. Returns ok or info about existing owner."""
    task = _require_lock_id(task_id)
    if not task:
        return error(f"invalid task id: {task_id}")
    agent = _require_agent_id(agent_id)
    if not agent:
        return error("valid agent_id required")
    LOCKS.mkdir(parents=True, exist_ok=True)
    d = LOCKS / task
    try:
        d.mkdir()
        (d / "owner").write_text(f"{agent}|{int(time.time())}|{ttl}\n")
        append_log("lock-acquire", task, agent)
        return ok()
    except FileExistsError:
        # Symlink-attack guard
        if d.is_symlink():
            return {"status": "locked", "error": "lock path is a symlink — refusing"}
        owner_file = d / "owner"
        o_agent, owner_error = _read_lock_owner(owner_file)
        if owner_error:
            return {"status": "locked", "error": owner_error}
        parts = owner_file.read_text().strip().split("|")
        o_ts, o_ttl = int(parts[1]), int(parts[2])
        age = int(time.time()) - o_ts
        if age > o_ttl:
            # Save the dead holder's uncommitted work before its lock goes
            # (t-2026-08-16-autosave-uncommitted-agent-wor).
            _autosave.evict(LOCKS, ACTIVE, task, o_agent)
            # Atomic stale takeover: rename stale dir away, then create fresh one.
            # If rename fails, another agent beat us to it — report race.
            stale_dir = d.with_name(f"{d.name}.stale.{os.getpid()}")
            try:
                os.rename(d, stale_dir)
            except OSError:
                return {"status": "locked", "error": "race: stale lock already taken"}
            try:
                d.mkdir()
                (d / "owner").write_text(f"{agent}|{int(time.time())}|{ttl}\n")
            except Exception:
                return {"status": "locked", "error": "race: mkdir failed after rename"}
            finally:
                shutil.rmtree(stale_dir, ignore_errors=True)
            append_log("lock-acquire", task, agent, f"took stale from {o_agent}")
            return ok(note=f"took stale lock from {o_agent} (age {age}s)")
        return {"status": "locked", "owner": o_agent, "age_seconds": age, "ttl": o_ttl}

@mcp.tool()
def release_lock(task_id: str, agent_id: str = "", force: bool = False, reason: str = "") -> dict:
    """Release a lock. Requires owner match, or explicit audited force."""
    task = _require_lock_id(task_id)
    if not task:
        return error(f"invalid task id: {task_id}")
    d = LOCKS / task
    if not d.exists():
        return {"status": "no_lock"}
    # Security: refuse to rmtree a symlink (symlink-attack guard).
    if d.is_symlink():
        return error("lock path is a symlink — refusing to remove")
    agent = _require_agent_id(agent_id)
    if not agent:
        return error("valid agent_id required")

    owner_file = d / "owner"
    owner, owner_error = _read_lock_owner(owner_file)

    if force:
        force_reason = _require_force_reason(reason)
        if not force_reason:
            return error("force reason required")
        note = f"force by {agent}: {force_reason}"
        if owner:
            note = f"{note} (owner={owner})"
        elif owner_error:
            note = f"{note} ({owner_error})"
    else:
        if owner_error:
            return error(owner_error)
        if owner != agent:
            return error(f"lock owned by {owner}, not {agent}")
        note = ""

    if d.is_symlink():
        return error("lock path is a symlink — refusing to remove")
    if not d.exists():
        return {"status": "no_lock"}

    shutil.rmtree(d)
    append_log("lock-release", task, agent, note)
    return ok()

@mcp.tool()
def refresh_lock(task_id: str, agent_id: str, ttl: int = LOCK_TTL_DEFAULT) -> dict:
    """Refresh TTL of a lock (only if you own it)."""
    task = _require_lock_id(task_id)
    if not task:
        return error(f"invalid task id: {task_id}")
    agent = _require_agent_id(agent_id)
    if not agent:
        return error("valid agent_id required")
    d = LOCKS / task
    owner_file = d / "owner"
    if not owner_file.exists():
        return error("no lock")
    o_agent, owner_error = _read_lock_owner(owner_file)
    if owner_error:
        return error(owner_error)
    if o_agent != agent:
        return error(f"not your lock (owner={o_agent})")
    owner_file.write_text(f"{agent}|{int(time.time())}|{ttl}\n")
    return ok()

@mcp.tool()
def lock_status(task_id: str = "") -> dict:
    """Status of one lock or all locks."""
    if task_id:
        task = _require_lock_id(task_id)
        if not task:
            return error(f"invalid task id: {task_id}")
        d = LOCKS / task
        if not d.exists():
            return {"status": "free"}
        owner_file = d / "owner"
        owner, owner_error = _read_lock_owner(owner_file)
        if owner_error:
            return {"status": "corrupt", "error": owner_error}
        parts = owner_file.read_text().strip().split("|")
        return {"status": "locked", "owner": owner,
                "age_seconds": int(time.time()) - int(parts[1]),
                "ttl": int(parts[2])}
    else:
        if not LOCKS.exists():
            return {"locks": []}
        out = []
        for d in LOCKS.iterdir():
            if not d.is_dir():
                continue
            owner_file = d / "owner"
            if owner_file.exists():
                parts = owner_file.read_text().strip().split("|")
                if len(parts) >= 3:
                    out.append({"task_id": d.name, "owner": parts[0],
                                "age_seconds": int(time.time()) - int(parts[1]),
                                "ttl": int(parts[2])})
        return {"locks": out}

@mcp.tool()
def cleanup_locks() -> dict:
    """Remove stale locks (TTL expired)."""
    if not LOCKS.exists():
        return {"cleaned": 0}
    n = 0
    now = int(time.time())
    for d in LOCKS.iterdir():
        if d.name.startswith("."):
            continue  # .reclaim.lock, .<tid>.autosaved breadcrumbs
        if not d.is_dir():
            continue
        # Security: skip symlinks — is_dir() follows symlinks so we must check
        # explicitly to avoid a symlink-attack via crafted .locks/ entries.
        if d.is_symlink():
            continue
        owner_file = d / "owner"
        if not owner_file.exists():
            shutil.rmtree(d); n += 1; continue
        parts = owner_file.read_text().strip().split("|")
        if len(parts) < 3:
            shutil.rmtree(d); n += 1; continue
        if now - int(parts[1]) > int(parts[2]):
            # Save the dead holder's uncommitted work before the lock goes
            # (t-2026-08-16-autosave-uncommitted-agent-wor).
            _autosave.evict(LOCKS, ACTIVE, d.name, parts[0])
            shutil.rmtree(d); n += 1
    return {"cleaned": n}

@mcp.tool()
def take_task(task_id: str, agent_id: str, ttl: int = LOCK_TTL_DEFAULT) -> dict:
    """Acquire lock and mark task in-progress.
    Returns error if already locked by someone else."""
    agent = _require_agent_id(agent_id)
    if not agent:
        return error("agent_id required")
    lock_result = acquire_lock(task_id, agent_id, ttl)
    if lock_result.get("status") != "ok":
        return lock_result
    try:
        queue.take(task_id, agent, BRAIN)
    except Exception as exc:
        release_lock(task_id, agent)
        return error(str(exc) or f"task {task_id} not found in active.md")
    append_log("task-start", task_id, agent_id)
    git_commit(f"task-start: {task_id} by {agent_id}")
    return ok(id=task_id, owner=agent_id)

@mcp.tool()
def release_task(task_id: str, agent_id: str = "") -> dict:
    """Mark in-progress task as open again, release lock."""
    agent = _require_agent_id(agent_id)
    if not agent:
        return error("agent_id required")
    try:
        queue.release(task_id, BRAIN, agent=agent)
    except Exception as exc:
        return error(str(exc) or "task not in-progress or not found")
    lock_result = release_lock(task_id, agent)
    if lock_result.get("status") == "error":
        return lock_result
    append_log("task-release", task_id, agent_id)
    git_commit(f"task-release: {task_id}")
    return ok()

@mcp.tool()
def complete_task(
    task_id: str,
    agent_id: str = "",
    model: str = "",
    summary: str = "",
    allow_unsigned: bool = False,
) -> dict:
    """Mark task done, move to done.md, release lock."""
    agent = _require_agent_id(agent_id)
    if not agent:
        return error("agent_id required")
    try:
        resolved = resolve_completion_model(model, allow_unsigned=allow_unsigned)
    except ModelSignatureError as exc:
        return error(str(exc))
    try:
        queue.complete(
            task_id, agent, resolved.value, BRAIN, allow_unsigned=resolved.unsigned,
        )
    except Exception as exc:
        return error(str(exc) or "task not found")
    lock_result = release_lock(task_id, agent)
    if lock_result.get("status") == "error":
        return lock_result
    append_log("task-done", task_id, agent_id, summary)
    try:
        import brain_webhook as _bwh
        import datetime as _dt
        _bwh.fire_task_done({
            "task_id": task_id,
            "agent_id": agent_id,
            "summary": summary,
            "timestamp": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    except Exception as _e:
        import sys as _sys
        _sys.stderr.write(f"warning: webhook failed: {_e}\n")
    git_commit(f"task-done: {task_id} by {agent_id or 'unknown'}")
    return ok(id=task_id)

@mcp.tool()
def get_task_bundle(task_id: str) -> dict:
    """Return task details + lock status + council files + index health hints in one call."""
    import json
    import datetime as _dt
    from common import brain_index
    # Task info
    task_info = None
    for path in [ACTIVE, DONE]:
        if not path.exists(): continue
        block = find_task_block(task_id)
        if block:
            info = parse_block(block)
            task_info = {
                "id": task_id,
                "state": brain_task_parser.state_from_char(info.get("state", " ")),
                "priority": info.get("prio", ""),
                "title": info.get("title", ""),
                "raw": block,
                "source": path.name,
            }
            break
    if task_info is None:
        task_info = {"id": task_id, "state": "not_found"}

    # Lock info
    lock_dir = LOCKS / task_id
    owner_path = lock_dir / "owner"
    lock_info = {"held": False}
    if owner_path.exists():
        parts = owner_path.read_text().strip().split("|")
        now = int(time.time())
        lock_info["held"] = True
        lock_info["owner"] = parts[0] if parts else ""
        if len(parts) >= 3:
            try:
                created = int(parts[1]); ttl = int(parts[2])
                age = max(0, now - created)
                lock_info.update({"age_seconds": age, "ttl_seconds": ttl, "stale": age > ttl})
            except ValueError: pass

    # Council info
    council_dir = BRAIN / "council" / task_id
    council_info = {"exists": council_dir.exists(), "files": []}
    if council_dir.exists():
        council_info["files"] = sorted(p.name for p in council_dir.iterdir() if p.is_file())

    # Index health hint
    idx_status = brain_index.index_status(BRAIN)
    if idx_status.get("status") == "missing":
        index_hint = {"health": "missing", "next_step": "brain-index rebuild"}
    else:
        index_hint = {
            "health": idx_status.get("health", "ok"),
            "next_step": "brain-index rebuild" if idx_status.get("health") == "stale" else "",
            "pages": idx_status.get("page_count", 0),
        }

    return {
        "task": task_info,
        "lock": lock_info,
        "council": council_info,
        "index": index_hint,
    }
