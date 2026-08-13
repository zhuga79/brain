"""Задачи, локи и сводка по ним."""

from __future__ import annotations

import os
import time
from collections import Counter
from pathlib import Path
from typing import Any


def brain_path(value: str | None = None) -> Path:
    return Path(value or os.environ.get("BRAIN_PATH") or (Path.home() / "brain")).expanduser()


def summarize_tasks(active: list[dict[str, Any]], done: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "active_count": len(active),
        "done_count": len(done),
        "states": dict(Counter(t["state"] for t in active)),
        "priorities": dict(Counter(t["priority"] for t in active)),
        "roles": dict(Counter(t["role"] or "unassigned" for t in active)),
        "modes": dict(Counter(t["mode"] or "unspecified" for t in active)),
        "surfaces": dict(Counter(t.get("surface") or "headless" for t in active)),
    }


def read_locks(brain: Path) -> list[dict[str, Any]]:
    locks_dir = brain / ".locks"
    if not locks_dir.exists():
        return []
    now = int(time.time())
    locks: list[dict[str, Any]] = []
    for lock_dir in sorted(p for p in locks_dir.iterdir() if p.is_dir()):
        owner_path = lock_dir / "owner"
        record: dict[str, Any] = {
            "task_id": lock_dir.name, "owner": "",
            "age_seconds": None, "ttl_seconds": None, "stale": None,
        }
        if owner_path.exists():
            parts = owner_path.read_text(encoding="utf-8", errors="replace").strip().split("|")
            if len(parts) >= 3:
                record["owner"] = parts[0]
                try:
                    created = int(parts[1])
                    ttl = int(parts[2])
                    record["age_seconds"] = max(0, now - created)
                    record["ttl_seconds"] = ttl
                    record["stale"] = record["age_seconds"] > ttl
                except ValueError:
                    pass
        locks.append(record)
    return locks
