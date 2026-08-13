"""Unified result helpers for Brain MCP tools.

Usage:
    from result import ok, error

    return ok(path="wiki/foo.md")
    return error("task not found", code="not_found")

Both helpers are backward-compatible:
- ok() always sets status="ok"
- error() always sets both status="error" and "error" key so old callers
  using ``if "error" in result`` continue to work.
"""
from typing import Any


def ok(**fields: Any) -> dict:
    """Return a success result dict with status='ok' and any extra fields."""
    return {"status": "ok", **fields}


def error(message: str, code: str = "generic", **fields: Any) -> dict:
    """Return an error result dict.

    Sets both ``status='error'`` (new style) and ``error=message`` key
    (old style) so callers using either convention work correctly.
    """
    return {"status": "error", "error": message, "code": code, **fields}
