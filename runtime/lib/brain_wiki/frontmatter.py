"""Frontmatter parsing and formatting for Brain wiki files.

Handles YAML-ish frontmatter as used by Obsidian/Brain wiki pages.
Intentionally dependency-free.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_strip_quotes(part.strip()) for part in inner.split(",") if part.strip()]
    return _strip_quotes(value)


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return "[" + ", ".join(str(item) for item in value) + "]"
    return str(value)


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse simple YAML-ish frontmatter from markdown content."""
    match = re.match(r"\A---[ \t]*\n(.*?)\n---[ \t]*\n?", content, re.S)
    if not match:
        return {}, content
    frontmatter: dict[str, Any] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = _parse_scalar(value)
    return frontmatter, content[match.end():]


def format_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    preferred = [
        "title",
        "type",
        "url",
        "author",
        "published",
        "fetched",
        "created",
        "updated",
        "curation",
        "protected",
        "last_reviewed_by",
        "last_reviewed_at",
        "source_policy",
        "tags",
        "sources",
        "related",
    ]
    keys = [key for key in preferred if key in frontmatter]
    keys.extend(sorted(key for key in frontmatter if key not in keys))

    lines = ["---"]
    for key in keys:
        lines.append(f"{key}: {_format_scalar(frontmatter[key])}")
    lines.extend(["---", "", body.lstrip()])
    return "\n".join(lines).rstrip() + "\n"


def as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def as_bool(value: Any, *, strict: bool = False, default: bool = False) -> bool:
    """Coerce *value* to bool.

    Truthy literals:  1, true, yes, y, on, t  (case-insensitive)
    Falsy literals:   0, false, no, n, off, f, ""  (case-insensitive)
    Bool pass-through: returned as-is.

    Unknown values:
      - strict=True  → raise ValueError("ambiguous bool: …")
      - strict=False → return *default* (default False)
    """
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on", "t"}:
        return True
    if s in {"0", "false", "no", "n", "off", "f", ""}:
        return False
    if strict:
        raise ValueError(f"ambiguous bool: {value!r}")
    return default


def validate_date(value: Any) -> bool:
    try:
        _dt.date.fromisoformat(str(value))
        return True
    except ValueError:
        return False
