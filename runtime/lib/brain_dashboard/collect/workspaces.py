"""Очередь предложений запуска и папки-workspace'ы вне дерева Brain."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import brain_workspace

from .tasks import brain_path


def collect_queue_proposals(brain: Path) -> dict[str, Any]:
    path = brain / ".brain" / "launch-queue" / "proposals.json"
    if not path.exists():
        return {
            "available": False,
            "path": str(path),
            "generated_at": "",
            "summary": {"pending": 0},
            "proposals": [],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {
            "available": False,
            "path": str(path),
            "error": str(exc),
            "generated_at": "",
            "summary": {"pending": 0},
            "proposals": [],
        }
    proposals = data.get("proposals") if isinstance(data, dict) else []
    if not isinstance(proposals, list):
        proposals = []
    summary = data.get("summary") if isinstance(data, dict) else {}
    if not isinstance(summary, dict):
        summary = {}
    summary.setdefault("pending", sum(1 for item in proposals if isinstance(item, dict) and item.get("status") == "pending"))
    return {
        "available": True,
        "path": str(path),
        "generated_at": data.get("generated_at", "") if isinstance(data, dict) else "",
        "summary": summary,
        "proposals": proposals,
        "error": "",
    }


# Обход дерева workspace'ов стоит секунды, а страница пересобирается часто.
_WS_CACHE: dict[str, Any] = {}


def _workspace_roots_from_env() -> tuple[list[Path], bool]:
    """Return (roots, auto). If no roots configured, default to scanning $HOME."""
    raw = os.environ.get("BRAIN_DASHBOARD_WORKSPACE_ROOTS") or os.environ.get("BRAIN_WORKSPACE_ROOTS") or ""
    roots = [Path(p).expanduser() for p in raw.split(os.pathsep) if p.strip()]
    if roots:
        return roots, False
    return [Path.home()], True


def _ws_cache_ttl() -> int:
    try:
        return int(os.environ.get("BRAIN_DASHBOARD_WS_CACHE_TTL", "60"))
    except ValueError:
        return 60


def _local_task_to_dict(task: Any | None) -> dict[str, str] | None:
    if task is None:
        return None
    return {
        "state": task.state,
        "priority": task.priority,
        "task_id": task.task_id,
        "title": task.title,
        "role": task.role,
        "acceptance": task.acceptance,
    }


def collect_workspaces() -> dict[str, Any]:
    import time
    roots, auto = _workspace_roots_from_env()
    cache_key = os.pathsep.join(str(r) for r in roots) + f"|auto={auto}"
    cached = _WS_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _ws_cache_ttl():
        return cached["data"]
    try:
        max_depth = int(os.environ.get("BRAIN_DASHBOARD_WS_MAX_DEPTH", "6"))
    except ValueError:
        max_depth = 6
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        infos = brain_workspace.discover_workspaces(
            roots, max_depth=max_depth, exclude=[brain_path()]
        )
    except OSError as exc:
        infos = []
        errors.append(str(exc))
    for info in infos:
        next_task = brain_workspace.next_local_task(
            info.path / "TASKS.md",
            brain_path=info.path / "BRAIN.md",
        )
        local_tasks = brain_workspace.parse_local_tasks(info.path / "TASKS.md")
        log_entries = brain_workspace.parse_local_log_entries(info.path / "LOG.md", 8)
        items.append({
            "path": str(info.path),
            "title": info.title,
            "mtime": info.mtime,
            "tasks": [
                {"state": t.state, "priority": t.priority, "task_id": t.task_id,
                 "title": t.title, "role": t.role}
                for t in local_tasks
            ],
            "log_entries": [
                {"timestamp": e.timestamp, "agent": e.agent, "summary": e.summary}
                for e in log_entries
            ],
            "has_tasks": info.has_tasks,
            "has_log": info.has_log,
            "open_tasks": info.open_tasks,
            "next_task": _local_task_to_dict(next_task),
            "latest_log": None
            if info.latest_log is None
            else {
                "timestamp": info.latest_log.timestamp,
                "agent": info.latest_log.agent,
                "summary": info.latest_log.summary,
            },
            "warnings": list(info.warnings),
        })
    items.sort(key=lambda it: it.get("mtime", 0.0), reverse=True)
    result = {
        "configured": True,
        "auto": auto,
        "roots": [str(root) for root in roots],
        "summary": {
            "count": len(items),
            "open_tasks": sum(int(item.get("open_tasks", 0) or 0) for item in items),
        },
        "items": items,
        "error": "; ".join(errors),
    }
    _WS_CACHE[cache_key] = {"ts": time.time(), "data": result}
    return result
