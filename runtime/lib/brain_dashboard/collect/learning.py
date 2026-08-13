"""Уроки, инциденты и экономия токенов."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def collect_learning_stats(brain: Path) -> dict[str, Any]:
    """Return read-only learning stats: counts and recent incidents (no full evidence)."""
    learning = brain / "learning"
    if not learning.exists():
        return {"available": False}

    def _count_files(sub: str) -> int:
        d = learning / sub
        return len(list(d.glob("*.md"))) if d.exists() else 0

    incidents_dir = learning / "incidents"
    recent_incidents: list[dict] = []
    if incidents_dir.exists():
        files = sorted(incidents_dir.glob("inc-*.md"), key=lambda p: p.name, reverse=True)
        for f in files[:5]:
            text = f.read_text(encoding="utf-8")
            # Parse minimal frontmatter
            fm: dict = {}
            if text.startswith("---"):
                end = text.find("\n---", 3)
                if end != -1:
                    for line in text[3:end].strip().splitlines():
                        if ":" in line:
                            k, _, v = line.partition(":")
                            k, v = k.strip(), v.strip()
                            if k not in ("id", "source", "task_id", "severity", "created"):
                                continue
                            fm[k] = v
            recent_incidents.append(fm)

    recent_lessons: list[dict] = []
    for status in ("pending", "approved", "active", "deprecated", "rejected"):
        lesson_dir = learning / "lessons" / status
        if not lesson_dir.exists():
            continue
        for f in sorted(lesson_dir.glob("les-*.md"), key=lambda p: p.name, reverse=True)[:8]:
            fm = _read_frontmatter(f, keep={
                "id", "incident_id", "status", "severity", "roles", "tags",
                "created", "updated", "approved_by", "rule", "confidence", "source",
            })
            rule = fm.get("rule", "")
            fm["path"] = str(f)
            fm["source"] = fm.get("source") or fm.get("incident_id") or ""
            fm["context_tokens_est"] = max(0, (len(rule) + 3) // 4)
            fm["injectable"] = fm.get("status") == "active" and bool(rule)
            fm["review_required"] = fm.get("status") in ("pending", "approved")
            recent_lessons.append(fm)
    recent_lessons.sort(key=lambda item: (item.get("updated") or item.get("created") or "", item.get("id", "")), reverse=True)

    return {
        "available": True,
        "counts": {
            "incidents": _count_files("incidents"),
            "pending": _count_files("lessons/pending"),
            "approved": _count_files("lessons/approved"),
            "active": _count_files("lessons/active"),
            "deprecated": _count_files("lessons/deprecated"),
        },
        "recent_incidents": recent_incidents,
        "recent_lessons": recent_lessons[:12],
        "injection_policy": {
            "active_rule_required": True,
            "pending_injected": False,
            "max_lessons": 5,
            "max_tokens": 800,
        },
    }


def _read_frontmatter(path: Path, keep: set[str]) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    fm: dict[str, Any] = {}
    if not text.startswith("---"):
        return fm
    end = text.find("\n---", 3)
    if end == -1:
        return fm
    for line in text[3:end].strip().splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k not in keep:
            continue
        if v.startswith("[") and v.endswith("]"):
            fm[k] = [x.strip() for x in v[1:-1].split(",") if x.strip()]
        else:
            fm[k] = v
    return fm


def collect_token_metrics(brain: Path, limit: int = 20) -> dict[str, Any]:
    paths = [
        brain / ".brain" / "token-metrics.jsonl",
        brain / ".brain" / "metrics" / "compact.jsonl",
    ]
    existing = [p for p in paths if p.exists()]
    if not existing:
        return {
            "available": False,
            "path": str(paths[0]),
            "paths": [str(p) for p in paths],
            "aggregate": {
                "commands": 0,
                "raw_bytes": 0,
                "compact_bytes": 0,
                "raw_tokens_est": 0,
                "compact_tokens_est": 0,
                "savings_percent": 0,
            },
            "recent": [],
        }
    records: list[dict[str, Any]] = []
    for path in existing:
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    item.setdefault("metrics_path", str(path))
                    records.append(item)
        except OSError:
            continue
    raw_bytes = sum(int(r.get("raw_bytes", 0) or 0) for r in records)
    compact_bytes = sum(int(r.get("compact_bytes", 0) or 0) for r in records)
    raw_tokens = sum(int(r.get("raw_tokens_est", 0) or 0) for r in records)
    compact_tokens = sum(int(r.get("compact_tokens_est", 0) or 0) for r in records)
    return {
        "available": True,
        "path": str(existing[0]),
        "paths": [str(p) for p in paths],
        "aggregate": {
            "commands": len(records),
            "raw_bytes": raw_bytes,
            "compact_bytes": compact_bytes,
            "raw_tokens_est": raw_tokens,
            "compact_tokens_est": compact_tokens,
            "savings_percent": round((1 - compact_bytes / raw_bytes) * 100, 2) if raw_bytes else 0,
        },
        "recent": records[-limit:][::-1],
    }
