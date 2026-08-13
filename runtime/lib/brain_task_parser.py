"""Shared task block parsing for Brain.

Single source of truth for block-level task operations.
All Python consumers delegate here instead of duplicating block parsing.

Higher-level task list parsing lives in brain_tasks.py (parse_tasks).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


from brain_core import grammar

TASK_BLOCK_RE = grammar.BLOCK_RE
"""Matches one complete task block: header + continuation lines."""

TASK_HEAD_RE = grammar.HEAD_RE
"""Matches the first line of a task block. Groups: state, priority, id, title.

The shape lives in brain_core.grammar so that readers and writers cannot drift
apart: a task written outside the reader's grammar used to save fine and then
vanish from `brain-task next`, the dashboard, the index and MCP."""


def parse_block(block: str) -> dict[str, Any]:
    """Parse a single task block string into a dict.

    Returns keys: state, prio, id, title, role, mode, deps,
                  council, by, started, parent, client, project,
                  acceptance, raw.

    Returns empty dict if the block cannot be parsed.
    """
    head = TASK_HEAD_RE.match(block)
    if not head:
        return {}
    state, prio, tid, title_line = head.groups()
    title = title_line.split("\n")[0]

    info: dict[str, Any] = {
        "state": state,
        # Приоритет необязателен: в очереди есть блоки без него, и раньше они
        # просто не парсились. Потребители подставляют значение в строку, поэтому
        # отсутствие отдаётся пустой строкой, а не None.
        "prio": prio or "",
        "id": tid,
        "title": title,
        "role": "",
        "mode": "solo",
        "surface": "",
        "gate": "",
        "deps": [],
        "council": [],
        "parent": "",
        # Заказчик — единица биллинга, проект — единица организации работы.
        # Оба значения содержат пробелы, поэтому разбираются по грамматике,
        # а не по `\\S+`.
        "client": "",
        "project": "",
        "acceptance": "",
        "by": "",
        "started": "",
        "raw": block,
    }

    # Поля берём через общую грамматику: она отличает поле от его имени,
    # упомянутого в тексте задачи. Раньше здесь был `re.search` по всей строке
    # без привязки к началу, и проза молча подменяла значение — последнее
    # вхождение выигрывало, а поля стоят выше прозы.
    single_token = ("role", "mode", "surface", "gate", "parent", "by", "started")
    with_spaces = ("client", "project", "acceptance")
    for line in block.split("\n"):
        fields = grammar.parse_fields(line)
        for name in single_token:
            if value := fields.get(name):
                info[name] = value.split()[0]
        for name in with_spaces:
            if name in fields:
                info[name] = fields[name]
        if "council" in fields:
            if m := re.match(r"\[([^\]]*)\]", fields["council"]):
                info["council"] = [x.strip() for x in m.group(1).split(",") if x.strip()]
        if "depends_on" in fields:
            if m := re.match(r"\[([^\]]*)\]", fields["depends_on"]):
                info["deps"] = [x.strip() for x in m.group(1).split(",") if x.strip()]

    return info


def find_blocks(text: str) -> list[str]:
    """Extract all task blocks from markdown text."""
    return [m.group(1) for m in TASK_BLOCK_RE.finditer(text)]


def find_block(text: str, task_id: str) -> str | None:
    """Find a single task block by exact ID. Returns the block string or None."""
    if m := grammar.block_re_for(task_id).search(text):
        return m.group(1)
    return None


def is_done(text: str, task_id: str) -> bool:
    """Check if a task is marked done ([x]) in the given text."""
    return bool(grammar.block_re_for(task_id, "x").search(text))


def state_from_char(ch: str) -> str:
    """Convert state char to human-readable string."""
    return {" ": "open", "~": "in_progress", "x": "done", "!": "blocked"}.get(ch, "unknown")


def is_valid_priority(prio: str) -> bool:
    """Check if a priority string is valid (P0-P3)."""
    return prio in ("P0", "P1", "P2", "P3")


def format_block(info: dict[str, Any]) -> str:
    """Convert a task dict back into a markdown block string."""
    lines = [f"- [{info['state']}] [{info['prio']}] {info['id']} — {info['title']}"]
    if info.get("role"):
        lines.append(f"      role: {info['role']}")
    if info.get("mode") and info["mode"] != "solo":
        lines.append(f"      mode: {info['mode']}")
    if info.get("surface"):
        lines.append(f"      surface: {info['surface']}")
    if info.get("gate"):
        lines.append(f"      gate: {info['gate']}")
    if info.get("deps"):
        lines.append(f"      depends_on: [{', '.join(info['deps'])}]")
    if info.get("council"):
        lines.append(f"      council: [{', '.join(info['council'])}]")
    if info.get("parent"):
        lines.append(f"      parent: {info['parent']}")
    if info.get("client"):
        lines.append(f"      client: {info['client']}")
    if info.get("project"):
        lines.append(f"      project: {info['project']}")
    if info.get("started"):
        lines.append(f"      started: {info['started']}")
    if info.get("by"):
        lines.append(f"      by: {info['by']}")
    if info.get("acceptance"):
        lines.append(f"      acceptance: {info['acceptance']}")
    return "\n".join(lines)


# Roles whose work inherently depends on a human in the loop.
# See wiki/decision-interactive-surface.md (t-2026-06-26).
INTERACTIVE_ROLES = {
    "taste-reviewer", "designer", "lawyer", "tax-advisor", "cfo",
    "negotiator", "arbiter", "accountant", "renovation-planner",
}


def effective_surface(info: dict[str, Any]) -> str:
    """Resolve the launch surface for a task.

    Explicit `surface:` always wins. Otherwise an explicit `gate:` or an
    interactive-by-nature role implies `interactive`. Default: `headless`.
    """
    explicit = (info.get("surface") or "").strip().lower()
    if explicit in ("interactive", "headless"):
        return explicit
    if (info.get("gate") or "").strip():
        return "interactive"
    if (info.get("role") or "").strip() in INTERACTIVE_ROLES:
        return "interactive"
    return "headless"
