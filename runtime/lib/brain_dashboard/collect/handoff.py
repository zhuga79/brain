"""Передача работы между агентами и состояние оператора."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def read_handoff_journal(brain: Path, limit: int = 10) -> list[dict[str, Any]]:
    handoff_dir = brain / "handoff"
    if not handoff_dir.exists():
        return []
    files = sorted(handoff_dir.glob("journal-*.ndjson"), reverse=True)
    entries: list[dict[str, Any]] = []
    for p in files:
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    entries.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    continue
                if len(entries) >= limit:
                    return entries
        except OSError:
            continue
    return entries


def collect_handoff_status(brain: Path) -> dict[str, Any]:
    """Return a safe summary of the latest orchestrator handoff artifact.

    The dashboard intentionally excludes Trigger Output Excerpt content because
    it can contain raw provider output, task excerpts or secrets.
    """
    path = brain / "handoff" / "ORCHESTRATOR_HANDOFF.md"
    base: dict[str, Any] = {
        "exists": False,
        "path": str(path),
        "generated": "",
        "reason": "",
        "from_agent": "",
        "to_role": "",
        "task": "",
        "next_task": "",
        "commands": [],
    }
    if not path.exists():
        return base
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        base.update({"exists": True, "error": str(exc)})
        return base

    def field(name: str) -> str:
        m = re.search(rf"^{re.escape(name)}:\s*(.*)$", text, re.M)
        return m.group(1).strip()[:240] if m else ""

    commands: list[str] = []
    m = re.search(r"^## Next Commands\s*```(?:bash)?\s*(.*?)^```", text, re.M | re.S)
    if m:
        for line in m.group(1).splitlines():
            clean = line.strip()
            if clean:
                commands.append(clean[:300])
            if len(commands) >= 8:
                break

    base.update({
        "exists": True,
        "generated": field("generated"),
        "reason": field("reason"),
        "from_agent": field("from_agent"),
        "to_role": field("to_role"),
        "task": field("task"),
        "next_task": field("next_task"),
        "commands": commands,
    })
    return base


def collect_operator_status(brain: Path) -> dict[str, Any]:
    """Return the latest operator console manifest without reading prompt/log content."""
    path = brain / ".brain" / "orchestrator" / "latest.json"
    base: dict[str, Any] = {
        "available": False,
        "path": str(path),
        "updated": "",
        "task": "",
        "role": "",
        "agent": "",
        "prompt": "",
        "log": "",
        "prompt_exists": False,
        "log_exists": False,
        "log_size": 0,
    }
    if not path.exists():
        return base
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        base.update({"available": True, "error": str(exc)})
        return base
    prompt = Path(str(data.get("prompt") or ""))
    log = Path(str(data.get("log") or ""))
    log_size = 0
    if log.exists():
        try:
            log_size = log.stat().st_size
        except OSError:
            log_size = 0
    base.update({
        "available": True,
        "updated": str(data.get("updated") or ""),
        "task": str(data.get("task") or ""),
        "role": str(data.get("role") or ""),
        "agent": str(data.get("agent") or ""),
        "prompt": str(prompt) if str(prompt) != "." else "",
        "log": str(log) if str(log) != "." else "",
        "prompt_exists": prompt.exists(),
        "log_exists": log.exists(),
        "log_size": log_size,
    })
    return base
