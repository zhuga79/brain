"""Frontmatter parsing and formatting for Brain wiki files.

Brain frontmatter is a **restricted subset of YAML**, not a look-alike format:
anything ``format_frontmatter`` writes must parse identically under a real
YAML parser (see ``tests/python/test_frontmatter.py::TestRealYamlCompat``),
and anything ``parse_frontmatter`` reads must either match the value a real
YAML parser would produce, or fail loudly via :class:`FrontmatterError`
instead of silently dropping or mangling data. See
``doctrine/frontmatter-format.md`` for the full decision record.

Supported subset, symmetric between writer and reader:
  - ``#`` comment lines and blank lines
  - top-level ``key: value`` (plain, single-quoted, double-quoted scalars)
  - inline flow lists ``key: [a, b, "c, d"]``
  - a block list opened by ``key:`` (empty value) followed by ``  - item``
    lines, one level of indentation, scalar items only
  - booleans ``true``/``false`` and the YAML 1.1 aliases ``yes``/``no``/
    ``on``/``off`` (all case-insensitive, matching a real YAML 1.1 parser)

Anything outside the subset (block scalars ``|``/``>``, flow mappings,
anchors/aliases/tags, nested block mappings, multi-line unquoted values)
raises :class:`FrontmatterError` on read instead of returning an empty or
truncated value.

Intentionally dependency-free: no ``import yaml`` at runtime (see
``pyproject.toml`` — ``brain-runtime`` ships with zero runtime dependencies
by design). Tests are free to cross-check against ``pyyaml``.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any


class FrontmatterError(ValueError):
    """Raised when frontmatter contains a construct outside the supported
    YAML subset. Read failures are loud on purpose: a silently empty or
    truncated value is worse than a stack trace pointing at the line."""


_KEY_RE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.\-]*):(.*)$")

# Chars that make a plain (unquoted) scalar ambiguous or illegal as the
# *first* character of a YAML plain scalar.
_PLAIN_UNSAFE_START = set("!&*-?:,[]{}#|>'\"%@`")
_RESERVED_WORDS = {"true", "false", "null", "~", "yes", "no", "on", "off"}
_NUMERIC_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")

_DOUBLE_QUOTE_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}
_DOUBLE_QUOTE_UNESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "r": "\r"}


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _needs_quoting(s: str) -> bool:
    """True when *s* cannot round-trip as a plain YAML scalar."""
    if s == "":
        return True
    if s != s.strip():
        return True
    if s[0] in _PLAIN_UNSAFE_START:
        return True
    if ": " in s or s.endswith(":"):
        return True
    if " #" in s:
        return True
    if any(ord(c) < 0x20 for c in s):
        return True
    if s.lower() in _RESERVED_WORDS:
        return True
    if _NUMERIC_RE.match(s):
        return True
    return False


def _needs_flow_quoting(s: str) -> bool:
    if _needs_quoting(s):
        return True
    return bool(set(s) & set(",[]{}"))


def _yaml_double_quote(s: str) -> str:
    return '"' + "".join(_DOUBLE_QUOTE_ESCAPES.get(ch, ch) for ch in s) + '"'


def _unescape_double_quoted(inner: str) -> str:
    out: list[str] = []
    i, n = 0, len(inner)
    while i < n:
        ch = inner[i]
        if ch == "\\" and i + 1 < n and inner[i + 1] in _DOUBLE_QUOTE_UNESCAPES:
            out.append(_DOUBLE_QUOTE_UNESCAPES[inner[i + 1]])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _unescape_single_quoted(inner: str) -> str:
    return inner.replace("''", "'")


def _parse_flow_list(inner: str, lineno: int) -> list[Any]:
    inner = inner.strip()
    if not inner:
        return []
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
            continue
        if ch == ",":
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if quote:
        raise FrontmatterError(f"строка {lineno}: незакрытая кавычка в списке")
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return [_parse_scalar_token(part, lineno) for part in parts if part]


def _parse_scalar_token(value: str, lineno: int) -> Any:
    value = value.strip()
    if not value:
        return ""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return _unescape_double_quoted(value[1:-1])
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return _unescape_single_quoted(value[1:-1])
    if value[0] in ('"', "'"):
        raise FrontmatterError(f"строка {lineno}: незакрытая кавычка в «{value}»")
    if value.startswith("[") and value.endswith("]"):
        return _parse_flow_list(value[1:-1], lineno)
    if value[0] in "&*!{" or value.startswith("|") or value.startswith(">"):
        raise FrontmatterError(
            f"строка {lineno}: неподдерживаемая YAML-конструкция «{value}»"
        )
    if value.lower() in {"true", "yes", "on"}:
        return True
    if value.lower() in {"false", "no", "off"}:
        return False
    return value


def _parse_scalar(value: str) -> Any:
    """Back-compat wrapper (no line number available)."""
    return _parse_scalar_token(value, 0)


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return "[" + ", ".join(_format_list_item(item) for item in value) + "]"
    return _format_str_scalar(str(value))


def _format_str_scalar(value: str) -> str:
    if _needs_quoting(value):
        return _yaml_double_quote(value)
    return value


def _format_list_item(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    s = str(value)
    if _needs_flow_quoting(s):
        return _yaml_double_quote(s)
    return s


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse Brain's restricted YAML-subset frontmatter from markdown content.

    Raises :class:`FrontmatterError` when a line is outside the supported
    subset (see module docstring) instead of silently skipping it.
    """
    match = re.match(r"\A---[ \t]*\n(.*?)\n---[ \t]*\n?", content, re.S)
    if not match:
        return {}, content
    frontmatter: dict[str, Any] = {}
    lines = match.group(1).splitlines()
    i, n = 0, len(lines)
    while i < n:
        raw_line = lines[i]
        lineno = i + 1
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent > 0:
            raise FrontmatterError(
                f"строка {lineno}: неожиданный отступ вне списка («{stripped}»)"
            )
        key_match = _KEY_RE.match(stripped)
        if not key_match:
            raise FrontmatterError(
                f"строка {lineno}: не «ключ: значение» и не элемент списка («{stripped}»)"
            )
        key, rest = key_match.group(1), key_match.group(2).strip()
        if rest == "":
            items: list[Any] = []
            j = i + 1
            consumed_any = False
            while j < n:
                item_line = lines[j]
                item_stripped = item_line.strip()
                if not item_stripped or item_stripped.startswith("#"):
                    j += 1
                    continue
                item_indent = len(item_line) - len(item_line.lstrip(" "))
                if item_indent == 0:
                    break
                if item_stripped == "-":
                    item_val = ""
                elif item_stripped.startswith("- "):
                    item_val = item_stripped[2:]
                else:
                    raise FrontmatterError(
                        f"строка {j + 1}: ожидался элемент списка «- значение» под «{key}:»"
                    )
                items.append(_parse_scalar_token(item_val, j + 1))
                consumed_any = True
                j += 1
            frontmatter[key] = items if consumed_any else None
            i = j
            continue
        frontmatter[key] = _parse_scalar_token(rest, lineno)
        i += 1
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
