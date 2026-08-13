"""Состояние сессий совета: чьи мнения написаны и готов ли синтез."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import brain_task_parser


def read_council(brain: Path) -> list[dict[str, Any]]:
    council_dir = brain / "council"
    if not council_dir.exists():
        return []
    expected_roles = _council_role_map(brain)
    councils: list[dict[str, Any]] = []
    for task_dir in sorted(p for p in council_dir.iterdir() if p.is_dir()):
        files = sorted(p.name for p in task_dir.iterdir() if p.is_file())
        role_names = expected_roles.get(task_dir.name) or sorted(
            p.stem for p in task_dir.glob("*.md") if p.name != "synthesis.md"
        )
        opinions = []
        for role in role_names:
            f = task_dir / f"{role}.md"
            opinions.append(_council_opinion_status(role, f))
        synthesis_path = task_dir / "synthesis.md"
        valid_count = sum(1 for item in opinions if item["status"] == "valid")
        all_valid = bool(opinions) and valid_count == len(opinions)
        if synthesis_path.exists():
            synthesis_status = "done" if _council_synthesis_done(synthesis_path) else "not_ready"
        else:
            synthesis_status = "ready" if all_valid else "not_ready"
        councils.append({
            "task_id": task_dir.name,
            "files": files,
            "file_count": len(files),
            "roles_required": role_names,
            "opinions": opinions,
            "synthesis": {
                "status": synthesis_status,
                "ready": all_valid and synthesis_status != "done",
                "path": str(synthesis_path),
            },
        })
    return councils


def _council_role_map(brain: Path) -> dict[str, list[str]]:
    """Return task_id -> expected council roles from active/done task blocks."""
    texts = []
    for rel in ("tasks/active.md", "tasks/done.md"):
        p = brain / rel
        if p.exists():
            texts.append(p.read_text(encoding="utf-8", errors="replace"))
    role_map: dict[str, list[str]] = {}
    for text in texts:
        for block in brain_task_parser.find_blocks(text):
            parsed = brain_task_parser.parse_block(block)
            if not parsed or not parsed.get("council"):
                continue
            role_map[parsed["id"]] = parsed["council"]
    return role_map


def _section_has_text(text: str, heading: str) -> bool:
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*\n(?P<body>.*?)(?=^## |\Z)",
        re.M | re.S,
    )
    m = pattern.search(text)
    return bool(m and m.group("body").strip())


def _frontmatter_value(text: str, key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def _council_opinion_status(role: str, path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"role": role, "status": "missing", "agent": "", "written": "", "path": str(path)}
    text = path.read_text(encoding="utf-8", errors="replace")
    agent = _frontmatter_value(text, "agent")
    written = _frontmatter_value(text, "written")
    valid = (
        agent not in ("", "TODO")
        and written not in ("", "TODO")
        and _section_has_text(text, "Position")
        and _section_has_text(text, "Recommendation")
    )
    return {
        "role": role,
        "status": "valid" if valid else "invalid",
        "agent": "" if agent == "TODO" else agent,
        "written": "" if written == "TODO" else written,
        "path": str(path),
    }


def _council_synthesis_done(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    synthesized = _frontmatter_value(text, "synthesized")
    arbiter = _frontmatter_value(text, "arbiter")
    return synthesized not in ("", "TODO") and arbiter not in ("", "TODO")
