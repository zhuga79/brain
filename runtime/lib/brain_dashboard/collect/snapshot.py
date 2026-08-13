"""Снимок состояния и разница с предыдущим — что изменилось со вчера."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SNAPSHOT_FILE = "brain-dashboard-snapshot.json"


def _snapshot_path(brain: Path) -> Path:
    return brain / "wiki" / "_views" / _SNAPSHOT_FILE


def load_snapshot(brain: Path) -> dict[str, Any] | None:
    p = _snapshot_path(brain)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _surfaces_counter(active: list[dict[str, Any]]) -> dict[str, int]:
    """Count effective surfaces across active tasks (interactive vs headless)."""
    c: dict[str, int] = {}
    for t in active:
        key = t.get("surface") or "headless"
        c[key] = c.get(key, 0) + 1
    return c


def save_snapshot(brain: Path, status: dict[str, Any]) -> None:
    snap = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task_ids": {t["id"]: t["state"] for t in status["tasks"]["active"]},
        "done_ids": [t["id"] for t in status["tasks"]["done"]],
        "lock_task_ids": [lock["task_id"] for lock in status["locks"]["items"]],
        "council_task_ids": [c["task_id"] for c in status["council"]["items"]],
        "surfaces": _surfaces_counter(status["tasks"]["active"]),
    }
    p = _snapshot_path(brain)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")


def compute_delta(old: dict[str, Any] | None, status: dict[str, Any]) -> dict[str, Any]:
    if old is None:
        return {"has_delta": False, "since": None}

    old_task_ids: dict[str, str] = old.get("task_ids", {})
    new_task_ids: dict[str, str] = {t["id"]: t["state"] for t in status["tasks"]["active"]}
    old_done: set[str] = set(old.get("done_ids", []))
    new_done: set[str] = {t["id"] for t in status["tasks"]["done"]}

    completed = sorted(new_done - old_done)
    added = sorted(set(new_task_ids) - set(old_task_ids))
    removed = sorted((set(old_task_ids) - set(new_task_ids)) - new_done)
    state_changed = sorted(
        tid for tid in set(old_task_ids) & set(new_task_ids)
        if old_task_ids[tid] != new_task_ids[tid]
    )

    old_locks: set[str] = set(old.get("lock_task_ids", []))
    new_locks: set[str] = {lock["task_id"] for lock in status["locks"]["items"]}
    old_councils: set[str] = set(old.get("council_task_ids", []))
    new_councils: set[str] = {c["task_id"] for c in status["council"]["items"]}

    return {
        "has_delta": True,
        "since": old.get("generated_at", "?"),
        "tasks_completed": completed,
        "tasks_added": added,
        "tasks_removed": removed,
        "tasks_state_changed": state_changed,
        "locks_acquired": sorted(new_locks - old_locks),
        "locks_released": sorted(old_locks - new_locks),
        "councils_new": sorted(new_councils - old_councils),
    }
