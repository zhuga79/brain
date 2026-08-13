"""Parsing for the machine-readable escalation matrix (dependency-free).

Reads ``doctrine/escalation-matrix.yaml`` — the single source of truth for the
zone → primary → escalate matrix that previously lived only as prose tables in
MEMORY.md (and its copy in runtime/templates/v2/MEMORY.md): it was not executed,
not validated, and drifted from ``roles/`` silently.

The file uses a deliberately restricted YAML subset so the validator stays
dependency-free on every install:

  - ``#`` comment lines and blank lines
  - top-level ``key: value`` (block scalars, inline lists ``[a, b]``)
  - a block list opened by ``key:`` with ``  - `` items
  - item sub-fields as ``    key: value``
  - plain, single-quoted and double-quoted scalars

Anything outside the subset is a parse error (fail closed): the matrix must
remain machine-validatable even on machines without a YAML library.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class EscalationParseError(ValueError):
    """Raised when the document is outside the supported YAML subset."""


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_strip_quotes(part.strip()) for part in inner.split(",") if part.strip()]
    if value.isdigit():
        return int(value)
    return _strip_quotes(value)


def _parse_key_value(lineno: int, text: str) -> tuple[str, str] | None:
    """Split ``key: value``; return None when the text is not a mapping entry."""
    key, sep, value = text.partition(":")
    if not sep:
        return None
    if not key.strip():
        raise EscalationParseError(f"строка {lineno}: пустой ключ в «{text}»")
    return key.strip(), value.strip()


def parse_document(text: str) -> dict[str, Any]:
    """Parse the restricted YAML subset into nested dicts/lists.

    Raises :class:`EscalationParseError` on anything outside the subset.
    """
    root: dict[str, Any] = {}
    current_list_key: str | None = None
    current_item: dict[str, Any] | None = None

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent > 0 and stripped.startswith("-"):
            if current_list_key is None:
                raise EscalationParseError(
                    f"строка {lineno}: элемент списка вне списка («{stripped}»)"
                )
            item: dict[str, Any] = {}
            root[current_list_key].append(item)
            current_item = item
            item_text = stripped[1:].strip()
            if item_text:
                pair = _parse_key_value(lineno, item_text)
                if pair is None:
                    raise EscalationParseError(
                        f"строка {lineno}: ожидалось «id: значение» («{item_text}»)"
                    )
                key, value = pair
                item[key] = _parse_scalar(value)
        elif indent == 0:
            current_list_key = None
            current_item = None
            pair = _parse_key_value(lineno, stripped)
            if pair is None:
                raise EscalationParseError(
                    f"строка {lineno}: ожидалось «ключ: значение» («{stripped}»)"
                )
            key, value = pair
            if value:
                root[key] = _parse_scalar(value)
            else:
                current_list_key = key
                root[key] = []
        else:
            if current_item is None:
                raise EscalationParseError(
                    f"строка {lineno}: вложенная строка вне элемента списка («{stripped}»)"
                )
            pair = _parse_key_value(lineno, stripped)
            if pair is None:
                raise EscalationParseError(
                    f"строка {lineno}: ожидалось «ключ: значение» («{stripped}»)"
                )
            key, value = pair
            current_item[key] = _parse_scalar(value)

    return root


def load_escalation_matrix(brain: "str | Path") -> tuple[dict[str, Any] | None, list[str]]:
    """Load and parse doctrine/escalation-matrix.yaml.

    Returns ``(data, errors)``. ``data`` is None when the file is absent,
    unreadable, or does not parse; in the error cases the problems are returned
    in *errors* so the caller can surface them as validation issues.
    """
    path = Path(brain) / "doctrine" / "escalation-matrix.yaml"
    if not path.is_file():
        return None, []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [f"не читается: {exc}"]
    try:
        data = parse_document(text)
    except EscalationParseError as exc:
        return None, [str(exc)]
    if not isinstance(data, dict):
        return None, ["корень должен быть объектом"]
    return data, []
