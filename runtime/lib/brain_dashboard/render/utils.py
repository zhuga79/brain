"""brain-dashboard HTML rendering utilities."""

from __future__ import annotations

import html as html_mod
from collections import Counter
from typing import Any


def h(text: Any) -> str:
    return html_mod.escape(str(text))


def counter_table(counter: dict[str, int], labels: dict[str, str] | None = None) -> str:
    if not counter:
        return "<em>—</em>"
    labels = labels or {}
    rows = "".join(
        f"<tr><td>{h(labels.get(k, k))}</td><td>{h(v)}</td></tr>"
        for k, v in sorted(counter.items())
    )
    return f'<table class="mini"><tr><th>Key</th><th>Count</th></tr>{rows}</table>'


def _option_list(values: list[str], all_label: str) -> str:
    options = [f"<option value=''>{h(all_label)}</option>"]
    for value in sorted(v for v in set(values) if v):
        options.append(f"<option value='{h(value)}'>{h(value)}</option>")
    return "".join(options)


def _provider_for_role(providers: dict[str, Any], role: str) -> str:
    info = (providers.get("roles") or {}).get(role or "")
    if not info:
        return ""
    preferred = info.get("preferred") or {}
    return str(preferred.get("provider") or "")


def _group_counts(tasks: list[dict[str, Any]], key_fn) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for task in tasks:
        key = key_fn(task) or "unassigned"
        counts[str(key)] += 1
    return dict(counts)


def _provider_badge(item: dict[str, Any] | None, cls: str) -> str:
    if not item:
        return "<em>none</em>"
    effort = f" {item.get('effort')}" if item.get("effort") else ""
    label = f"{item.get('provider', '')}/{item.get('model', '')}{effort}"
    reason = item.get("reason", "")
    title = f" title='{h(reason)}'" if reason else ""
    return f"<span class='badge {h(cls)}'{title}>{h(label)}</span>"

def _surface_badge(surface: str) -> str:
    """Return a small badge for the task launch surface (interactive/headless)."""
    cls = "state-progress" if surface == "interactive" else "state-open"
    return f"<span class='badge {h(cls)}' title='surface: {h(surface)}'>{h(surface)}</span>"

