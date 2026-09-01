from __future__ import annotations

import os
import re
import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from brain_core import atomic, grammar
from brain_core.model_signature import AUDIT_OP, resolve_completion_model

UTC = timezone.utc


IGNORED_DIRS = {
    ".git",
    ".mcp-rag",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "semantic_env",
    "venv",
}

TASK_RE = re.compile(
    r"^- \[(?P<mark>[ xX~!])\] \[(?P<priority>P[0-9])\] (?P<task_id>\S+)\s+(?P<sep>—|-)\s+(?P<title>.+)$"
)
LOG_RE = re.compile(r"^## (?P<timestamp>[^|]+?) \| (?P<agent>[^|]+?) \| (?P<summary>.+)$")
WORKSPACE_LOCK_NAME = ".workspace-queue.lock"
WORKSPACE_JOURNAL_NAME = ".workspace-queue-journal.json"
WORKSPACE_JOURNAL_VERSION = "1"



TASK_KEYWORD_ROLE_MAP = {
    "test": "developer",
    "tests": "developer",
    "fix": "developer",
    "bug": "developer",
    "refactor": "reviewer",
    "doc": "copywriter",
    "docs": "copywriter",
    "deploy": "delivery",
    "security": "security",
    "UI": "designer",
    "UX": "designer",
    "design": "designer",
    "research": "researcher",
    "architect": "architect",
    "plan": "architect",
}


@dataclass(frozen=True)
class LocalTask:
    state: str
    priority: str
    task_id: str
    title: str
    role: str = ""
    acceptance: str = ""
    depends_on: tuple[str, ...] = ()



@dataclass(frozen=True)
class LocalLogEntry:
    timestamp: str
    agent: str
    summary: str


@dataclass(frozen=True)
class WorkspaceRolePolicy:
    workspace_type: str = ""
    primary_role: str = ""
    core: tuple[str, ...] = ()
    available: tuple[str, ...] = ()
    gated: tuple[str, ...] = ()
    blocked: tuple[str, ...] = ()
    requires_user_approval: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkspaceInfo:
    path: Path
    brain_file: Path
    title: str
    has_tasks: bool
    has_log: bool
    open_tasks: int = 0
    latest_log: LocalLogEntry | None = None
    warnings: tuple[str, ...] = ()
    mtime: float = 0.0


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def _state_from_mark(mark: str) -> str:
    return {
        " ": "open",
        "x": "done",
        "X": "done",
        "~": "in-progress",
        "!": "blocked",
    }.get(mark, "open")


_PLACEHOLDER_TITLES = {"<name>", "<project name>", "workspace: <name>", "project", "workspace"}


def _read_title(brain_file: Path) -> str:
    """First H1 of BRAIN.md, cleaned. Strips a leading 'Workspace:'/'Project:'
    prefix and ignores unfilled placeholders; falls back to the folder name."""
    try:
        text = brain_file.read_text(encoding="utf-8")
    except OSError:
        return brain_file.parent.name
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            for prefix in ("Workspace:", "Project:"):
                if title.lower().startswith(prefix.lower()):
                    title = title[len(prefix):].strip()
            if title and title.lower() not in _PLACEHOLDER_TITLES and "<" not in title:
                return title
            break
    return brain_file.parent.name


def _infer_role_from_title(title: str) -> str:
    lower_title = title.lower()
    for keyword, role in TASK_KEYWORD_ROLE_MAP.items():
        if keyword in lower_title:
            return role
    return "developer"


def _field_value(line: str, name: str) -> str:
    """Значение поля из строки продолжения блока.

    Границу значения знает `brain_core.grammar`: несколько полей в одной
    строке разделяются двумя и более пробелами. Здесь был свой разбор через
    `split(":", 1)`, и `role: lawyer   mode: solo` давал роль `lawyer   mode:
    solo` — после чего ни фильтр по роли, ни политика workspace задачу не
    находили.
    """
    match = grammar.field_re(name).search(line)
    return match.group(1).strip() if match else ""


def _parse_depends_on(value: str) -> tuple[str, ...]:
    """Parse a depends_on field value into a tuple of task ids.

    Canonical form is the bracketed list ``[task-a, task-b]``, but hand-written
    local queues also use the bare forms — a single id ``task-a`` and a bare
    comma list ``task-a, task-b`` — so both are accepted. Empty (``[]`` or an
    empty string) yields no dependencies. Unbalanced brackets and empty
    components (``[task-a,]``, ``task-a,,task-b``) are rejected fail-closed.
    """
    value = value.strip()
    if not value:
        return ()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
    elif value.startswith("[") or value.endswith("]"):
        raise ValueError(f"Malformed depends_on list (unbalanced brackets): {value}")
    else:
        inner = value
    if not inner:
        return ()
    # Split by comma, strip whitespace
    raw_deps = [dep.strip() for dep in inner.split(",")]
    # Reject empty components (fail-closed)
    for dep in raw_deps:
        if not dep:
            raise ValueError(f"Malformed depends_on list (empty component): {value}")
    return tuple(raw_deps)


def _validate_depends_on(task_id: str, depends_on: tuple[str, ...], all_task_ids: set[str]) -> None:
    """Validate depends_on for a single task.

    Raises ValueError with precise message for:
    - Self-dependency
    - Duplicate dependencies
    - Missing dependencies (not in all_task_ids)
    """
    if task_id in depends_on:
        raise ValueError(f"Task {task_id} has self-dependency in depends_on")

    # Check for duplicates
    seen = set()
    for dep in depends_on:
        if dep in seen:
            raise ValueError(f"Task {task_id} has duplicate dependency: {dep}")
        seen.add(dep)

    # Check for missing dependencies
    for dep in depends_on:
        if dep not in all_task_ids:
            raise ValueError(f"Task {task_id} has missing dependency: {dep}")


def _detect_cycles(tasks: list[LocalTask]) -> None:
    """Detect cycles in the dependency graph.

    Raises ValueError if a cycle is found.
    """
    # Build adjacency list
    graph: dict[str, list[str]] = {task.task_id: list(task.depends_on) for task in tasks}

    # Kahn's algorithm / DFS cycle detection
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def dfs(node: str) -> None:
        visited.add(node)
        rec_stack.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_stack:
                raise ValueError(f"Dependency cycle detected involving: {neighbor}")
        rec_stack.remove(node)

    for task in tasks:
        if task.task_id not in visited:
            dfs(task.task_id)


def parse_local_tasks_from_text(text: str) -> list[LocalTask]:
    tasks: list[LocalTask] = []
    current: dict[str, str] | None = None
    current_depends_on_seen = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = TASK_RE.match(line)
        if match:
            if current is not None:
                tasks.append(LocalTask(**current))
            task_id = match.group("task_id")
            current = {
                "state": _state_from_mark(match.group("mark")),
                "priority": match.group("priority"),
                "task_id": task_id,
                "title": match.group("title").strip(),
                "role": "",
                "acceptance": "",
                "depends_on": (),
            }
            current_depends_on_seen = False
            continue
        if current is None:
            continue
        stripped = line.strip()
        # Duplicate depends_on within the same continuation line: the shared
        # grammar collapses repeated fields into a dict, so detect them here
        # before the dict loses entries. Works regardless of field order.
        # Only true field starts count — prose/backticked mentions do not.
        if grammar.count_field_starts(stripped, "depends_on") > 1:
            raise ValueError(f"Task {current['task_id']} has duplicate depends_on field")
        # Use shared grammar to parse all fields on the line
        fields = grammar.parse_fields(stripped)
        for name, value in fields.items():
            if name == "role":
                current["role"] = value
            elif name == "acceptance":
                current["acceptance"] = value
            elif name == "depends_on":
                if current_depends_on_seen:
                    raise ValueError(f"Task {current['task_id']} has duplicate depends_on field")
                current_depends_on_seen = True
                current["depends_on"] = _parse_depends_on(value)
    if current is not None:
        tasks.append(LocalTask(**current))

    # Reject duplicate task IDs deterministically before any graph/selection/mutation
    seen_ids: dict[str, int] = {}
    for i, task in enumerate(tasks):
        if task.task_id in seen_ids:
            raise ValueError(f"Duplicate task ID: {task.task_id} (first at line ~{seen_ids[task.task_id]}, second at line ~{i})")
        seen_ids[task.task_id] = i

    # Validate all depends_on after parsing all tasks (for forward references)
    all_task_ids = {task.task_id for task in tasks}
    for task in tasks:
        _validate_depends_on(task.task_id, task.depends_on, all_task_ids)

    # Detect cycles
    _detect_cycles(tasks)

    return tasks


def parse_local_tasks(path: Path) -> list[LocalTask]:
    if not path.exists():
        return []
    return parse_local_tasks_from_text(path.read_text(encoding="utf-8"))


def parse_local_log_entries(path: Path, limit: int = 8) -> list[LocalLogEntry]:
    """Parse up to `limit` log entries (file order, top = most recent)."""
    if not path.exists():
        return []
    out: list[LocalLogEntry] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        m = LOG_RE.match(raw_line.strip())
        if m:
            out.append(LocalLogEntry(
                timestamp=m.group("timestamp").strip(),
                agent=m.group("agent").strip(),
                summary=m.group("summary").strip(),
            ))
            if len(out) >= limit:
                break
    return out


def parse_local_log(path: Path) -> LocalLogEntry | None:
    if not path.exists():
        return None
    latest: LocalLogEntry | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LOG_RE.match(line.strip())
        if match:
            latest = LocalLogEntry(
                timestamp=match.group("timestamp").strip(),
                agent=match.group("agent").strip(),
                summary=match.group("summary").strip(),
            )
    return latest


def _read_section_lists(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    lists: dict[str, list[str]] = {}
    current_key = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            current_key = stripped[3:].strip()
            lists.setdefault(current_key, [])
            continue
        if stripped.endswith(":") and not stripped.startswith("-"):
            current_key = stripped[:-1].strip()
            lists.setdefault(current_key, [])
            continue
        if current_key and stripped.startswith("-"):
            value = stripped[1:].strip()
            if value:
                lists[current_key].append(value)
    return lists


def _read_scalar(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    prefix = f"{key}:"
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith(prefix):
            return stripped.split(":", 1)[1].strip()
    return ""


def _roles(values: list[str]) -> tuple[str, ...]:
    roles = [value for value in values if value and value.lower() != "none"]
    return tuple(roles)


def parse_workspace_policy(path: Path) -> WorkspaceRolePolicy:
    lists = _read_section_lists(path)
    core = _roles(lists.get("core", []))
    available = _roles(lists.get("available", []))
    gated = _roles(lists.get("gated", []))
    blocked = _roles(lists.get("blocked", []))
    if not (core or available or gated or blocked):
        available = _roles(lists.get("Allowed Roles", []))
    return WorkspaceRolePolicy(
        workspace_type=_read_scalar(path, "type"),
        primary_role=_read_scalar(path, "primary_role"),
        core=core,
        available=available,
        gated=gated,
        blocked=blocked,
        requires_user_approval=tuple(lists.get("requires_user_approval", [])),
    )


def is_role_allowed(policy: WorkspaceRolePolicy, role: str) -> bool:
    if not role:
        return True
    if role in policy.blocked:
        return False
    allowed = set(policy.core) | set(policy.available) | set(policy.gated)
    if not allowed:
        return True
    return role in allowed


def _all_deps_met(task: LocalTask, all_tasks: list[LocalTask]) -> bool:
    """Check if all dependencies of a task are in 'done' state."""
    if not task.depends_on:
        return True
    task_by_id = {t.task_id: t for t in all_tasks}
    for dep_id in task.depends_on:
        dep_task = task_by_id.get(dep_id)
        if dep_task is None or dep_task.state != "done":
            return False
    return True


def next_local_task(path: Path, role: str = "", brain_path: Path | None = None) -> LocalTask | None:
    policy = parse_workspace_policy(brain_path) if brain_path is not None else None
    if policy is not None and role and not is_role_allowed(policy, role):
        return None
    all_tasks = parse_local_tasks(path)
    for task in all_tasks:
        if task.state != "open":
            continue
        if policy is not None and task.role and not is_role_allowed(policy, task.role):
            continue
        if role and task.role and task.role != role:
            continue
        if role and not task.role:
            if _all_deps_met(task, all_tasks):
                return task
            continue
        if not role or task.role == role:
            if _all_deps_met(task, all_tasks):
                return task
    return None


def _mark_for_state(state: str) -> str:
    marks = {
        "open": " ",
        "in-progress": "~",
        "done": "x",
        "blocked": "!",
    }
    if state not in marks:
        raise ValueError(f"Unsupported local task state: {state}")
    return marks[state]


def _task_file_text(path: Path) -> str:
    return atomic.read_text(path)


def _atomic_write(path: Path, text: str) -> None:
    atomic.write_text(path, text, prefix=".workspace.")


def _queue_lock(workspace: Path):
    return atomic.file_lock(workspace.resolve() / WORKSPACE_LOCK_NAME)


def _journal_path(workspace: Path) -> Path:
    return workspace.resolve() / WORKSPACE_JOURNAL_NAME


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _field_line(name: str, value: str) -> str:
    return f"      {name}: {value}"


def _strip_task_fields(lines: list[str], names: tuple[str, ...]) -> list[str]:
    prefixes = tuple(f"{name}:" for name in names)
    return [line for line in lines if not line.lstrip().startswith(prefixes)]


def _extract_task_field(lines: list[str], name: str) -> str:
    prefix = f"{name}:"
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.split(":", 1)[1].strip()
    return ""


def _replace_task_block_text(
    text: str,
    task_id: str,
    state: str,
    *,
    from_states: tuple[str, ...],
    mutate_body,
) -> tuple[str, LocalTask]:
    target_mark = _mark_for_state(state)
    lines = text.splitlines()
    updated: list[str] = []
    changed = False
    i = 0
    while i < len(lines):
        line = lines[i]
        match = TASK_RE.match(line.rstrip())
        if not match or match.group("task_id") != task_id:
            updated.append(line)
            i += 1
            continue

        current_state = _state_from_mark(match.group("mark"))
        if from_states and current_state not in from_states:
            expected = ", ".join(from_states)
            raise ValueError(f"Local task {task_id} has state {current_state}; expected state {expected}")

        body_lines: list[str] = []
        j = i + 1
        while j < len(lines) and not TASK_RE.match(lines[j].rstrip()):
            body_lines.append(lines[j])
            j += 1
        body_lines = mutate_body(body_lines, current_state)
        updated.append(
            f"- [{target_mark}] [{match.group('priority')}] {task_id} "
            f"{match.group('sep')} {match.group('title').strip()}"
        )
        updated.extend(body_lines)
        changed = True
        i = j
    if not changed:
        raise ValueError(f"Local task not found: {task_id}")

    new_text = "\n".join(updated) + "\n"
    parsed = next((task for task in parse_local_tasks_from_text(new_text) if task.task_id == task_id), None)
    if parsed is None:
        raise ValueError(f"Local task not found after update: {task_id}")
    return new_text, parsed


def update_local_task_state(
    path: Path,
    task_id: str,
    state: str,
    from_states: tuple[str, ...] = (),
) -> LocalTask:
    if not path.exists():
        raise FileNotFoundError(path)
    new_text, task = _replace_task_block_text(
        path.read_text(encoding="utf-8"),
        task_id,
        state,
        from_states=from_states,
        mutate_body=lambda body_lines, _current_state: body_lines,
    )
    _atomic_write(path, new_text)
    return task


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append_local_log(
    path: Path,
    *,
    timestamp: str,
    agent: str,
    summary: str,
    detail: str = "",
) -> None:
    with _queue_lock(path.parent):
        _recover_workspace_transaction(path.parent)
        content = _task_file_text(path).rstrip()
        if not content:
            content = "# Local Log"
        _atomic_write(path, _append_local_log_text(content, timestamp=timestamp, agent=agent, summary=summary, detail=detail))


def _append_local_log_text(
    content: str,
    *,
    timestamp: str,
    agent: str,
    summary: str,
    detail: str = "",
) -> str:
    content = content.rstrip()
    if not content:
        content = "# Local Log"
    entry = f"## {timestamp} | {agent} | {summary}"
    if detail:
        entry = f"{entry}\n\n- {detail}"
    return f"{content}\n\n{entry}\n"


def _write_workspace_journal(
    workspace: Path,
    *,
    operation: str,
    task_id: str,
    tasks_before: str,
    log_before: str,
    tasks_after: str,
    log_after: str,
) -> None:
    atomic.write_json(
        _journal_path(workspace),
        {
            "version": WORKSPACE_JOURNAL_VERSION,
            "operation": operation,
            "task_id": task_id,
            "tasks_before_hash": _sha256_text(tasks_before),
            "log_before_hash": _sha256_text(log_before),
            "tasks_after_hash": _sha256_text(tasks_after),
            "log_after_hash": _sha256_text(log_after),
            "tasks_after": tasks_after,
            "log_after": log_after,
        },
    )


def _recover_workspace_transaction(workspace: Path) -> None:
    journal_path = _journal_path(workspace)
    payload = atomic.read_json(journal_path)
    if not payload:
        return
    if not isinstance(payload, dict) or payload.get("version") != WORKSPACE_JOURNAL_VERSION:
        raise ValueError(f"Invalid workspace journal: {journal_path}")
    tasks_path = workspace / "TASKS.md"
    log_path = workspace / "LOG.md"
    tasks_text = _task_file_text(tasks_path)
    log_text = _task_file_text(log_path)
    tasks_before_hash = str(payload.get("tasks_before_hash", ""))
    log_before_hash = str(payload.get("log_before_hash", ""))
    tasks_after = str(payload.get("tasks_after", ""))
    log_after = str(payload.get("log_after", ""))
    if str(payload.get("tasks_after_hash", "")) != _sha256_text(tasks_after):
        raise ValueError(f"Invalid workspace journal: {journal_path}")
    if str(payload.get("log_after_hash", "")) != _sha256_text(log_after):
        raise ValueError(f"Invalid workspace journal: {journal_path}")
    tasks_state = _journal_file_state(
        label="TASKS.md",
        current_text=tasks_text,
        before_hash=tasks_before_hash,
        after_hash=str(payload.get("tasks_after_hash", "")),
        journal_path=journal_path,
    )
    log_state = _journal_file_state(
        label="LOG.md",
        current_text=log_text,
        before_hash=log_before_hash,
        after_hash=str(payload.get("log_after_hash", "")),
        journal_path=journal_path,
    )
    if tasks_state == "before":
        _atomic_write(tasks_path, tasks_after)
    if log_state == "before":
        _atomic_write(log_path, log_after)
    journal_path.unlink(missing_ok=True)


def _journal_file_state(
    *,
    label: str,
    current_text: str,
    before_hash: str,
    after_hash: str,
    journal_path: Path,
) -> str:
    current_hash = _sha256_text(current_text)
    if current_hash == after_hash:
        return "after"
    if current_hash == before_hash:
        return "before"
    raise ValueError(f"Workspace recovery conflict for {label}: current file matches neither before nor after in {journal_path}")


def _run_workspace_transaction(
    workspace: Path,
    *,
    operation: str,
    task_id: str,
    mutate,
) -> LocalTask:
    workspace = workspace.resolve()
    tasks_path = workspace / "TASKS.md"
    log_path = workspace / "LOG.md"
    with _queue_lock(workspace):
        _recover_workspace_transaction(workspace)
        tasks_before = _task_file_text(tasks_path)
        log_before = _task_file_text(log_path)
        tasks_after, log_after, task = mutate(tasks_before, log_before)
        _write_workspace_journal(
            workspace,
            operation=operation,
            task_id=task_id,
            tasks_before=tasks_before,
            log_before=log_before,
            tasks_after=tasks_after,
            log_after=log_after,
        )
        _atomic_write(tasks_path, tasks_after)
        _atomic_write(log_path, log_after)
        _journal_path(workspace).unlink(missing_ok=True)
        return task


def take_local_task(workspace: Path, task_id: str, agent: str) -> LocalTask:
    timestamp = utc_timestamp()

    def mutate(tasks_before: str, log_before: str) -> tuple[str, str, LocalTask]:
        all_tasks = parse_local_tasks_from_text(tasks_before)
        existing = next((task for task in all_tasks if task.task_id == task_id), None)
        if existing is None:
            raise ValueError(f"Local task not found: {task_id}")

        # Check dependencies before any mutation
        if not _all_deps_met(existing, all_tasks):
            unmet = [dep for dep in existing.depends_on if dep not in {t.task_id for t in all_tasks if t.state == "done"}]
            raise ValueError(f"Local task {task_id} has unmet dependencies: {', '.join(unmet)}")

        if existing.state == "in-progress":
            body_lines = []
            lines = tasks_before.splitlines()
            for index, line in enumerate(lines):
                match = TASK_RE.match(line.rstrip())
                if match and match.group("task_id") == task_id:
                    cursor = index + 1
                    while cursor < len(lines) and not TASK_RE.match(lines[cursor].rstrip()):
                        body_lines.append(lines[cursor])
                        cursor += 1
                    break
            if _extract_task_field(body_lines, "by") == agent:
                return tasks_before, log_before, existing
        tasks_after, task = _replace_task_block_text(
            tasks_before,
            task_id,
            "in-progress",
            from_states=("open",),
            mutate_body=lambda body_lines, _current_state: (
                _strip_task_fields(body_lines, ("started", "by", "completed", "model"))
                + [_field_line("started", timestamp), _field_line("by", agent)]
            ),
        )
        log_after = _append_local_log_text(
            log_before,
            timestamp=timestamp,
            agent=agent,
            summary=f"took {task_id}",
            detail=f"Moved {task_id} to in-progress.",
        )
        return tasks_after, log_after, task

    return _run_workspace_transaction(workspace, operation="take", task_id=task_id, mutate=mutate)


def complete_local_task(
    workspace: Path,
    task_id: str,
    agent: str,
    model: str,
    summary: str = "",
    *,
    allow_unsigned: bool = False,
) -> LocalTask:
    resolved = resolve_completion_model(model, allow_unsigned=allow_unsigned)
    model = resolved.value
    timestamp = utc_timestamp()
    summary = summary or f"completed {task_id}"

    def mutate(tasks_before: str, log_before: str) -> tuple[str, str, LocalTask]:
        all_tasks = parse_local_tasks_from_text(tasks_before)
        existing = next((task for task in all_tasks if task.task_id == task_id), None)
        if existing is None:
            raise ValueError(f"Local task not found: {task_id}")

        # Check dependencies before any mutation
        if not _all_deps_met(existing, all_tasks):
            unmet = [dep for dep in existing.depends_on if dep not in {t.task_id for t in all_tasks if t.state == "done"}]
            raise ValueError(f"Local task {task_id} has unmet dependencies: {', '.join(unmet)}")

        if existing and existing.state == "done":
            body_lines = []
            lines = tasks_before.splitlines()
            for index, line in enumerate(lines):
                match = TASK_RE.match(line.rstrip())
                if match and match.group("task_id") == task_id:
                    cursor = index + 1
                    while cursor < len(lines) and not TASK_RE.match(lines[cursor].rstrip()):
                        body_lines.append(lines[cursor])
                        cursor += 1
                    break
            if _extract_task_field(body_lines, "by") == agent and _extract_task_field(body_lines, "model") == model:
                return tasks_before, log_before, existing

        def update_body(body_lines: list[str], _current_state: str) -> list[str]:
            owner = _extract_task_field(body_lines, "by")
            if not owner:
                raise ValueError(f"Local task owner missing: {task_id}")
            if owner != agent:
                raise ValueError(f"Local task {task_id} is owned by {owner}, not {agent}")
            return _strip_task_fields(body_lines, ("completed", "model")) + [
                _field_line("model", model),
                _field_line("completed", timestamp),
            ]

        tasks_after, task = _replace_task_block_text(
            tasks_before,
            task_id,
            "done",
            from_states=("in-progress",),
            mutate_body=update_body,
        )
        detail = f"Moved {task_id} to done."
        if resolved.unsigned:
            detail = f"{detail} {AUDIT_OP} {resolved.audit_extra}"
        log_after = _append_local_log_text(
            log_before,
            timestamp=timestamp,
            agent=agent,
            summary=summary,
            detail=detail,
        )
        return tasks_after, log_after, task

    return _run_workspace_transaction(workspace, operation="complete", task_id=task_id, mutate=mutate)


def _workspace_info(folder: Path, brain_file: Path) -> WorkspaceInfo:
    tasks_path = folder / "TASKS.md"
    log_path = folder / "LOG.md"
    # Discovery/listing is a read path: a single malformed TASKS.md must not
    # hide the workspace or abort the whole scan. Fall back to an empty task
    # list — the workspace still shows with its title, log and mtime. The
    # enforcement ops (next/take/complete_local_task) call parse_local_tasks
    # directly and stay fail-closed on the same file.
    try:
        local_tasks = parse_local_tasks(tasks_path)
    except ValueError:
        local_tasks = []
    mtimes = [f.stat().st_mtime for f in (brain_file, tasks_path, log_path) if f.exists()]
    return WorkspaceInfo(
        path=folder,
        brain_file=brain_file,
        title=_read_title(brain_file),
        has_tasks=tasks_path.exists(),
        has_log=log_path.exists(),
        open_tasks=sum(1 for task in local_tasks if task.state == "open"),
        latest_log=parse_local_log(log_path),
        mtime=max(mtimes) if mtimes else 0.0,
    )


def discover_workspaces(
    roots: list[Path],
    max_depth: int = 6,
    exclude: list[Path] | None = None,
) -> list[WorkspaceInfo]:
    """Find folder-native workspaces by their BRAIN.md marker.

    Walks each root with directory pruning (IGNORED_DIRS + dotfolders) and a
    depth cap so scanning a large home directory stays fast. A folder with a
    BRAIN.md is a workspace; its subtree is not descended further.
    """
    found: list[WorkspaceInfo] = []
    seen: set[Path] = set()
    excluded = {Path(e).expanduser().resolve() for e in (exclude or [])}
    for root in roots:
        root = root.expanduser().resolve()
        if not root.exists():
            continue
        root_depth = len(root.parts)

        def _excluded(folder: Path) -> bool:
            rfolder = folder.resolve()
            return any(rfolder == ex or ex in rfolder.parents for ex in excluded)

        for dirpath, dirnames, filenames in os.walk(root):
            cur = Path(dirpath)
            # skip excluded subtrees entirely (e.g. the host Brain repo, its
            # templates/, fixtures and worktrees)
            if _excluded(cur):
                dirnames[:] = []
                continue
            depth = len(cur.parts) - root_depth
            if depth >= max_depth:
                dirnames[:] = []
            # prune heavy/hidden dirs in place so os.walk skips their subtrees
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
            if "BRAIN.md" in filenames:
                folder = cur.resolve()
                if folder in seen or _excluded(folder):
                    dirnames[:] = []
                    continue
                seen.add(folder)
                found.append(_workspace_info(folder, folder / "BRAIN.md"))
                dirnames[:] = []  # do not nest workspaces
    found.sort(key=lambda w: w.title.lower())
    return found


def find_nearest_workspace(path: Path) -> Path | None:
    current = path.expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "BRAIN.md").exists():
            return candidate
    return None

def _ascii_slug(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    ascii_title = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-")
    return slug


def _generate_task_id(title: str, counter: int) -> str:
    slug = _ascii_slug(title)[:24].strip("-") or "task"
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
    return f"t-{counter:03d}-{slug}-{digest}"


def parse_project_descriptor(content: str) -> dict:
    """Parses a project descriptor into name, goal, tasks, and roles."""
    result = {
        "name": "",
        "goal": "",
        "tasks": [],
        "roles": []
    }
    content_str = content.strip()
    try:
        if content_str.startswith("{"):
            import json
            data = json.loads(content_str)
            result["name"] = str(data.get("name", ""))
            result["goal"] = str(data.get("goal", ""))
            result["tasks"] = [str(t) for t in data.get("tasks", [])]
            result["roles"] = [str(r) for r in data.get("roles", [])]
        else:
            import re
            name_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            if name_match:
                result["name"] = name_match.group(1).strip()

            goal_match = re.search(r"^##\s+Goal\s*\n(.*?)(?=\n##|\Z)", content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
            if goal_match:
                result["goal"] = goal_match.group(1).strip()

            tasks_match = re.search(r"^##\s+Tasks\s*\n(.*?)(?=\n##|\Z)", content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
            if tasks_match:
                tasks_text = tasks_match.group(1)
                for line in tasks_text.splitlines():
                    line = line.strip()
                    if line.startswith("- ") or line.startswith("* "):
                        result["tasks"].append(line[2:].strip())

            roles_match = re.search(r"^##\s+Roles\s*\n(.*?)(?=\n##|\Z)", content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
            if roles_match:
                roles_text = roles_match.group(1)
                for line in roles_text.splitlines():
                    line = line.strip()
                    if line.startswith("- ") or line.startswith("* "):
                        result["roles"].append(line[2:].strip())

        if not result["name"] and not result["goal"]:
            raise ValueError("Descriptor must have at least a name or a goal")

        return result
    except Exception as e:
        raise ValueError(f"Failed to parse descriptor: {e}")


def convert_folder_to_workspace(folder_path: Path, descriptor: dict) -> WorkspaceInfo:
    """Converts a folder into a workspace project by creating BRAIN.md and TASKS.md."""
    folder_path.mkdir(parents=True, exist_ok=True)
    brain_file = folder_path / "BRAIN.md"
    tasks_file = folder_path / "TASKS.md"

    if not brain_file.exists():
        name = descriptor.get("name") or folder_path.name
        goal = descriptor.get("goal", "") or "Опиши назначение проекта в одно предложение."
        created = datetime.now(UTC).strftime("%Y-%m-%d")
        brain_content = (
            f"# {name}\n\n"
            f"> {goal}\n\n"
            f"- **created:** {created}\n"
            f"- **status:** active\n"
            f"- **primary role:** developer\n\n"
            f"## Purpose\n\n{goal}\n"
        )
        brain_file.write_text(brain_content, encoding="utf-8")

    existing_tasks = parse_local_tasks(tasks_file)
    existing_task_titles = {task.title for task in existing_tasks}

    new_task_lines = []
    if not tasks_file.exists():
        new_task_lines.append("# Tasks\n\n")

    task_counter = len(existing_tasks) + 1
    for item in descriptor.get("tasks", []):
        task_title = ""
        task_role = ""
        task_acceptance = ""

        if isinstance(item, str):
            task_title = item.strip()
            task_role = _infer_role_from_title(task_title)
        elif isinstance(item, dict):
            task_title = item.get("title", "").strip()
            explicit_role = item.get("role", "").strip()
            task_role = explicit_role if explicit_role else _infer_role_from_title(task_title)
            task_acceptance = item.get("acceptance", "").strip()

        if not task_title:
            continue

        if task_title in existing_task_titles:
            continue

        task_id = _generate_task_id(task_title, task_counter)
        existing_task_titles.add(task_title) # Add to set to catch duplicates within the same descriptor list

        task_line = f"- [ ] [P2] {task_id} - {task_title}\n"
        if task_role:
            task_line += f"      role: {task_role}\n"
        if task_acceptance:
            task_line += f"      acceptance: {task_acceptance}\n"

        new_task_lines.append(task_line)
        task_counter += 1

    if new_task_lines:
        with open(tasks_file, "a", encoding="utf-8") as f:
            f.writelines(new_task_lines)

    workspaces = discover_workspaces([folder_path])
    if not workspaces:
        raise ValueError("Failed to create or find workspace after conversion.")

    return workspaces[0]
