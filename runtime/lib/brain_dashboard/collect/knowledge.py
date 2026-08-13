"""Индекс, граф связей, журнал операций и представления Obsidian."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import brain_index
import brain_wiki


def read_index(brain: Path) -> dict[str, Any]:
    status = brain_index.index_status(brain)
    if status.get("status") == "missing":
        status["next_step"] = "brain-index rebuild"
    elif status.get("health") == "stale":
        status["next_step"] = "brain-index rebuild"
    else:
        status["next_step"] = ""
    return status


def read_graph(brain: Path) -> dict[str, Any]:
    """Read Knowledge Graph stats from .brain/index/graph.json."""
    graph_path = brain_index.index_dir(brain) / "graph.json"
    if not graph_path.exists():
        return {"available": False, "nodes": 0, "edges": 0, "node_types": {}, "edge_types": {}}
    from collections import Counter
    try:
        data = brain_index.load_json(graph_path, {"nodes": [], "edges": []})
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        node_types = Counter(n["type"] for n in nodes)
        edge_types = Counter(e.get("type", "relates_to") for e in edges)
        return {
            "available": True,
            "nodes": len(nodes),
            "edges": len(edges),
            "node_types": dict(node_types.most_common()),
            "edge_types": dict(edge_types.most_common()),
        }
    except Exception:
        return {"available": False, "nodes": 0, "edges": 0, "node_types": {}, "edge_types": {}}


_LOG_LINE_RE = re.compile(
    r"^## \[(?P<ts>[^\]]+)\]\s+(?P<op>[^|]+?)\s*\|\s*(?P<task>[^|]*?)\s*\|\s*(?P<agent>[^|]*?)\s*\|\s*(?P<extra>.*)$"
)


def read_audit_log(brain: Path, limit: int = 20, task_filter: str = "") -> list[dict[str, str]]:
    log_path = brain / "wiki" / "log.md"
    if not log_path.exists():
        return []
    entries = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _LOG_LINE_RE.match(line.strip())
        if not m:
            continue
        entry = {k: m.group(k).strip() for k in ("ts", "op", "task", "agent", "extra")}
        if task_filter and task_filter not in entry["task"]:
            continue
        entries.append(entry)
    return entries[-limit:][::-1]  # newest first, capped at limit


def read_obsidian_views(brain: Path) -> dict[str, bool]:
    views_dir = brain / "wiki" / "_views"
    return {name: (views_dir / name).exists() for name in brain_wiki.OBSIDIAN_EXPECTED_VIEWS}


def read_wiki_pages(brain: Path) -> list[dict[str, Any]]:
    """Страницы вики из собранного индекса. Отсутствие индекса — пустой список."""
    pages_file = brain / ".brain" / "index" / "pages.json"
    if not pages_file.exists():
        return []
    try:
        data = json.loads(pages_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    pages = data.get("pages")
    return pages if isinstance(pages, list) else []


def obsidian_vault_name(brain: Path) -> str:
    """Имя хранилища Obsidian: из окружения, из его конфига или по имени папки.

    Нужно, чтобы собрать ссылку obsidian://open — то есть это данные среды, а
    не оформление, и читаются они здесь, а не в слое рендеринга.
    """
    name = os.environ.get("BRAIN_OBSIDIAN_VAULT", "").strip()
    if name:
        return name
    try:
        config = json.loads(
            (Path.home() / ".config" / "obsidian" / "obsidian.json").read_text(encoding="utf-8")
        )
        for vault in (config.get("vaults") or {}).values():
            path = vault.get("path", "")
            if path:
                return path.rstrip("/").split("/")[-1]
    except (OSError, json.JSONDecodeError):
        pass
    return brain.name or "brain"


def collect_wiki(brain: Path) -> dict[str, Any]:
    """Всё, что нужно секции страниц вики: сами страницы и адресация Obsidian."""
    return {
        "pages": read_wiki_pages(brain),
        "vault": obsidian_vault_name(brain),
        "link_prefix": f"{brain.name}-wiki",
        "indexed": (brain / ".brain" / "index" / "pages.json").exists(),
    }
