"""Shared task parsing library for Brain.

Builds on brain_task_parser for block-level operations; provides
higher-level list/load functions.

Priority scale: P0 (urgent) / P1 (important) / P2 (when hands free) / P3 (backlog)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import brain_task_parser

TASK_RE = brain_task_parser.TASK_HEAD_RE
"""Alias for backward compatibility."""

PRIORITY_LEVELS = ["P0", "P1", "P2", "P3"]
"""Valid priority levels in descending order of urgency."""


def parse_tasks(text: str) -> list[dict[str, Any]]:
    """Parse active.md or done.md text into list of task dicts.

    Uses brain_task_parser for block-level parsing.
    Normalises keys: priority (not prio), depends_on (not deps).
    """
    tasks: list[dict[str, Any]] = []
    for block in brain_task_parser.find_blocks(text):
        info = brain_task_parser.parse_block(block)
        if not info:
            continue
        tasks.append({
            "id": info["id"],
            "title": info["title"],
            "state": info["state"],
            "priority": info["prio"],
            "role": info.get("role", ""),
            "mode": info.get("mode", "solo"),
            "parent": info.get("parent", ""),
            "client": info.get("client", ""),
            "project": info.get("project", ""),
            "depends_on": info.get("deps", []),
            "surface": brain_task_parser.effective_surface(info),
        })
    return tasks


def find_task(text: str, task_id: str) -> dict[str, Any] | None:
    """Find a single task by exact ID. Returns None if not found."""
    for task in parse_tasks(text):
        if task["id"] == task_id:
            return task
    return None


def load_active(brain: Path) -> list[dict[str, Any]]:
    """Load and parse active tasks from brain path."""
    path = brain / "tasks" / "active.md"
    return parse_tasks(path.read_text(encoding="utf-8", errors="replace")) if path.exists() else []


def load_done(brain: Path) -> list[dict[str, Any]]:
    """Load and parse done tasks from brain path."""
    path = brain / "tasks" / "done.md"
    return parse_tasks(path.read_text(encoding="utf-8", errors="replace")) if path.exists() else []


# Re-export from brain_task_parser for backward compatibility
is_valid_priority = brain_task_parser.is_valid_priority
