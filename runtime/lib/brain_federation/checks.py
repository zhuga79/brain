"""11 check_* functions for brain_federation preflight checks."""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .core import (
    Finding,
    RUNTIME_PATHS,
    GENERATED_IGNORE_PATTERNS,
    SECRET_RE,
    SEVERITIES,
)
from .git_ops import git_run, git_show


def comparable(task: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(task.get("title", "")),
        str(task.get("role", "")),
        str(task.get("mode", "")),
        str(task.get("acceptance", "")),
    )


def check_duplicates(tasks: list[dict[str, Any]], code: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: dict[str, dict[str, Any]] = {}
    for task in tasks:
        task_id = task["id"]
        if task_id not in seen:
            seen[task_id] = task
            continue
        findings.append(
            Finding(
                code,
                "block",
                f"{task['path']}:{task['line']}",
                f"duplicate task id: {task_id}",
                "deduplicate task records before importing",
            )
        )
        if comparable(task) != comparable(seen[task_id]):
            findings.append(
                Finding(
                    "task-field-conflict",
                    "block",
                    f"{task['path']}:{task['line']}",
                    f"task {task_id} has conflicting title, role, mode or acceptance",
                    "resolve the task metadata conflict manually",
                )
            )
    return findings


def check_cross_file_conflicts(active: list[dict[str, Any]], done: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    done_by_id = {task["id"]: task for task in done}
    for task in active:
        done_task = done_by_id.get(task["id"])
        if not done_task:
            continue
        if task["state"] in (" ", "~") and done_task["state"] == "x":
            findings.append(
                Finding(
                    "task-done-open-conflict",
                    "block",
                    f"{task['path']}:{task['line']}",
                    f"task {task['id']} is open/in-progress and done in compared inputs",
                    "choose one lifecycle state before import",
                )
            )
        if comparable(task) != comparable(done_task):
            findings.append(
                Finding(
                    "task-field-conflict",
                    "block",
                    f"{task['path']}:{task['line']}",
                    f"task {task['id']} metadata differs between active and done",
                    "merge title, role, mode and acceptance manually",
                )
            )
    return findings


def path_matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return path == pattern[:-1] or path.startswith(pattern)
    return path == pattern


def check_runtime_paths(repo: Path, changed_paths: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    reported: set[str] = set()
    for pattern in RUNTIME_PATHS:
        target = repo / pattern.rstrip("/")
        exists = target.exists()
        changed = any(path_matches(path, pattern) for path in changed_paths)
        if not exists and not changed:
            continue
        path = pattern.rstrip("/")
        if path in reported:
            continue
        reported.add(path)
        findings.append(
            Finding(
                "runtime-file-included",
                "block",
                path,
                "runtime-local/generated Brain file must not be synced",
                "remove from commit/import and keep it ignored",
            )
        )
    return findings


def check_raw_rewrites(name_status: list[tuple[str, str]]) -> list[Finding]:
    findings: list[Finding] = []
    for status, path in name_status:
        if path.startswith("raw/") and status[:1] in {"M", "D", "R", "C"}:
            findings.append(
                Finding(
                    "raw-rewrite",
                    "block",
                    path,
                    "existing raw source file was modified or deleted",
                    "raw sources are immutable; ingest a new source instead",
                )
            )
    return findings


def _frontmatter(path: Path) -> dict[str, str]:
    """Read frontmatter from a markdown file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip().lower()] = value.strip().strip("'\"").lower()
    return data


def check_wiki_curation(repo: Path, changed_paths: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(changed_paths):
        if not path.startswith("wiki/") or not path.endswith(".md"):
            continue
        page = repo / path
        fm = _frontmatter(page)
        if fm.get("protected") == "true":
            findings.append(
                Finding(
                    "protected-wiki-edit",
                    "block",
                    path,
                    "changed wiki page is protected",
                    "human approval is required before changing protected pages",
                )
            )
        if fm.get("curation") == "human":
            findings.append(
                Finding(
                    "human-curated-wiki-edit",
                    "block",
                    path,
                    "changed wiki page is human-curated",
                    "manual edits have priority over generated source imports",
                )
            )
    return findings


def _collect_commands(value: Any, prefix: str = "") -> dict[str, str]:
    commands: dict[str, str] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            if key == "command" and isinstance(child, str):
                commands[child_prefix] = child
            else:
                commands.update(_collect_commands(child, child_prefix))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            child_prefix = f"{prefix}[{idx}]"
            commands.update(_collect_commands(child, child_prefix))
    return commands


def check_provider_matrix(repo: Path, changed_paths: set[str]) -> list[Finding]:
    path = "wiki/provider-matrix.json"
    if path not in changed_paths and not (repo / path).exists():
        return []
    if path not in changed_paths:
        return []
    findings = [
        Finding(
            "provider-matrix-change",
            "review",
            path,
            "provider routing matrix changed",
            "review role priority and fallback behavior before merge",
        )
    ]
    old_text = git_show(repo, path)
    current_path = repo / path
    if old_text is None or not current_path.exists():
        return findings
    try:
        old_data = json.loads(old_text)
        new_data = json.loads(current_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return findings
    if _collect_commands(old_data) != _collect_commands(new_data):
        findings.append(
            Finding(
                "provider-command-change",
                "review",
                path,
                "provider command changed inside matrix",
                "verify command syntax and quota/fallback implications",
            )
        )
    return findings


def check_possible_secrets(repo: Path) -> list[Finding]:
    diff = git_run(repo, "diff", "HEAD")
    findings: list[Finding] = []
    for line in diff.stdout.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if SECRET_RE.search(line):
            findings.append(
                Finding(
                    "possible-secret",
                    "warn",
                    "",
                    "diff contains a possible token, password or API key",
                    "remove secrets before sharing or syncing",
                )
            )
            break
    return findings


def check_optional_secret_scanner(repo: Path) -> list[Finding]:
    command = os.environ.get("BRAIN_SECRET_SCANNER_CMD", "").strip()
    if not command:
        return []
    try:
        args = shlex.split(command)
    except ValueError as exc:
        return [
            Finding(
                "secret-scanner-unavailable",
                "warn",
                "",
                f"optional secret scanner command is invalid: {exc}",
                "fix BRAIN_SECRET_SCANNER_CMD or unset it to use the built-in fallback only",
            )
        ]
    if not args:
        return []
    try:
        res = subprocess.run(
            [*args, str(repo)],
            cwd=str(repo),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [
            Finding(
                "secret-scanner-unavailable",
                "warn",
                "",
                f"optional secret scanner unavailable: {exc}",
                "using built-in regex fallback only; no scanner install was attempted",
            )
        ]

    findings: list[Finding] = []
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            findings.append(
                Finding(
                    "secret-scanner-finding",
                    "warn",
                    "",
                    line.strip(),
                    "optional scanner emitted a non-JSON finding",
                )
            )
            continue
        code = str(item.get("code") or "secret-scanner-finding")
        severity = str(item.get("severity") or "warn")
        if severity not in SEVERITIES:
            severity = "warn"
        findings.append(
            Finding(
                code,
                severity,
                str(item.get("path") or ""),
                str(item.get("message") or "optional scanner finding"),
                str(item.get("hint") or ""),
            )
        )
    if res.returncode not in (0, 1):
        findings.append(
            Finding(
                "secret-scanner-unavailable",
                "warn",
                "",
                f"optional secret scanner exited {res.returncode}",
                "scanner failure is non-fatal; built-in fallback still ran",
            )
        )
    return findings


def check_gitignore(repo: Path) -> list[Finding]:
    path = repo / ".gitignore"
    if not path.exists():
        return [
            Finding(
                "missing-generated-ignore",
                "warn",
                ".gitignore",
                "generated runtime paths are not ignored",
                "add Brain runtime/generated paths to .gitignore",
            )
        ]
    lines = {
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = [pattern for pattern in GENERATED_IGNORE_PATTERNS if pattern not in lines]
    if not missing:
        return []
    return [
        Finding(
            "missing-generated-ignore",
            "warn",
            ".gitignore",
            "generated runtime paths are not fully ignored",
            "missing: " + ", ".join(missing),
        )
    ]


def check_learning_status_conflict(repo: Path) -> list[Finding]:
    base = repo / "learning" / "lessons"
    if not base.exists():
        return []
    by_id: dict[str, list[str]] = {}
    for status in ("pending", "approved", "active", "deprecated", "rejected"):
        folder = base / status
        if not folder.exists():
            continue
        for lesson in folder.glob("les-*.md"):
            by_id.setdefault(lesson.stem, []).append(status)
    findings: list[Finding] = []
    for lesson_id, statuses in sorted(by_id.items()):
        if len(statuses) > 1:
            findings.append(
                Finding(
                    "learning-status-conflict",
                    "review",
                    f"learning/lessons/{lesson_id}.md",
                    f"lesson appears in multiple statuses: {', '.join(statuses)}",
                    "choose one lifecycle status before merge",
                )
            )
    return findings


def check_council_synthesis_stale(repo: Path) -> list[Finding]:
    base = repo / "council"
    if not base.exists():
        return []
    findings: list[Finding] = []
    for task_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        synthesis = task_dir / "synthesis.md"
        if not synthesis.exists():
            continue
        syn_mtime = synthesis.stat().st_mtime
        stale = [
            path.name
            for path in task_dir.glob("*.md")
            if path.name != "synthesis.md" and path.stat().st_mtime > syn_mtime
        ]
        if stale:
            findings.append(
                Finding(
                    "council-synthesis-stale",
                    "review",
                    str(synthesis.relative_to(repo)),
                    "council role opinion changed after synthesis",
                    "rerun brain-council synthesize before accepting the merge",
                )
            )
    return findings


def check_lock_conflicts(repo: Path, changed_paths: set[str]) -> list[Finding]:
    """Warn if modified tasks are currently locked locally."""
    findings: list[Finding] = []
    locks_dir = repo / ".locks"
    if not locks_dir.exists():
        return []

    # Get local active locks
    try:
        active_locks = [p.name for p in locks_dir.iterdir() if p.is_dir() and p.name.startswith("t-")]
    except OSError:
        return []

    if not active_locks:
        return []

    # If any task file is changed, we check if our locked tasks are affected.
    # For now, if active.md or done.md changed, we emit a warning for all active locks.
    task_files = {"tasks/active.md", "tasks/done.md"}
    if any(p in changed_paths for p in task_files):
        for tid in sorted(active_locks):
            findings.append(
                Finding(
                    "federated-lock-warning",
                    "review",
                    f".locks/{tid}",
                    f"task {tid} is locked locally but task files changed in remote",
                    "verify your local work against remote changes after sync",
                )
            )
    return findings
