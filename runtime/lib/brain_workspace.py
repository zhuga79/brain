from __future__ import annotations

import os
import re
import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from brain_core import grammar

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


def parse_local_tasks(path: Path) -> list[LocalTask]:
    if not path.exists():
        return []
    tasks: list[LocalTask] = []
    current: dict[str, str] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        match = TASK_RE.match(line)
        if match:
            if current is not None:
                tasks.append(LocalTask(**current))
            current = {
                "state": _state_from_mark(match.group("mark")),
                "priority": match.group("priority"),
                "task_id": match.group("task_id"),
                "title": match.group("title").strip(),
                "role": "",
                "acceptance": "",
            }
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("role:"):
            current["role"] = _field_value(stripped, "role")
        elif stripped.startswith("acceptance:"):
            current["acceptance"] = _field_value(stripped, "acceptance")
    if current is not None:
        tasks.append(LocalTask(**current))
    return tasks


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


def next_local_task(path: Path, role: str = "", brain_path: Path | None = None) -> LocalTask | None:
    policy = parse_workspace_policy(brain_path) if brain_path is not None else None
    if policy is not None and role and not is_role_allowed(policy, role):
        return None
    for task in parse_local_tasks(path):
        if task.state != "open":
            continue
        if policy is not None and task.role and not is_role_allowed(policy, task.role):
            continue
        if role and task.role and task.role != role:
            continue
        if role and not task.role:
            return task
        if not role or task.role == role:
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


def update_local_task_state(
    path: Path,
    task_id: str,
    state: str,
    from_states: tuple[str, ...] = (),
) -> LocalTask:
    if not path.exists():
        raise FileNotFoundError(path)
    target_mark = _mark_for_state(state)
    lines = path.read_text(encoding="utf-8").splitlines()
    updated: list[str] = []
    changed = False
    for line in lines:
        match = TASK_RE.match(line.rstrip())
        if match and match.group("task_id") == task_id:
            current_state = _state_from_mark(match.group("mark"))
            if from_states and current_state not in from_states:
                expected = ", ".join(from_states)
                raise ValueError(f"Local task {task_id} has state {current_state}; expected state {expected}")
            line = (
                f"- [{target_mark}] [{match.group('priority')}] {task_id} "
                f"{match.group('sep')} {match.group('title').strip()}"
            )
            changed = True
        updated.append(line)
    if not changed:
        raise ValueError(f"Local task not found: {task_id}")
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    for task in parse_local_tasks(path):
        if task.task_id == task_id:
            return task
    raise ValueError(f"Local task not found after update: {task_id}")


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
    if path.exists():
        content = path.read_text(encoding="utf-8").rstrip()
        if not content:
            content = "# Local Log"
    else:
        content = "# Local Log"
    entry = f"## {timestamp} | {agent} | {summary}"
    if detail:
        entry = f"{entry}\n\n- {detail}"
    path.write_text(f"{content}\n\n{entry}\n", encoding="utf-8")


def _workspace_info(folder: Path, brain_file: Path) -> WorkspaceInfo:
    tasks_path = folder / "TASKS.md"
    log_path = folder / "LOG.md"
    local_tasks = parse_local_tasks(tasks_path)
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
