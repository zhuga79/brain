#!/usr/bin/env python3
"""Dependency-free machine indexes and BM25 search for Brain."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sys
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal

import brain_wiki
import brain_tasks


INDEX_VERSION = 1
INDEX_DIR = Path(".brain") / "index"


# ---------------------------------------------------------------------------
# TypedDicts
# ---------------------------------------------------------------------------

try:
    from typing import TypedDict
except ImportError:  # Python < 3.8 fallback (shouldn't happen, but safe)
    TypedDict = None  # type: ignore[assignment,misc]


if TypedDict is not None:
    class PageRecord(TypedDict, total=False):
        """Record for a wiki page in the index.

        total=False: many fields are optional; slug and path are always present.
        """
        slug: str                    # required: filename stem
        path: str                    # required: relative path from brain root
        title: str
        type: str                    # concept / decision / source-summary / ...
        tags: list
        created: str
        updated: str
        curation: str                # "agent" | "human"
        protected: bool
        source_policy: str           # "advisory" | "required" | "ignored"
        sources: list
        related: list
        implements: list
        refutes: list
        depends_on: list
        links: list
        missing_links: list
        word_count: int
        mtime: float

    class RawRecord(TypedDict, total=False):
        """Record for a raw source file in the index.

        total=False: most fields are optional (raw files may lack frontmatter).
        """
        slug: str
        path: str
        title: str
        type: str
        url: str
        fetched: str
        word_count: int
        mtime: float

    class SearchDoc(TypedDict):
        """A document in the BM25 search corpus."""
        id: str
        path: str
        kind: str          # "wiki" | "raw" | "task"
        page_type: str
        title: str
        text: str
        mtime: float

    class WikiNode(TypedDict, total=False):
        """A node in the knowledge graph.

        total=False: canvas field only present for canvas nodes.
        """
        id: str
        type: str          # "wiki" | "task" | "canvas_text" | "canvas_file"
        title: str
        canvas: str        # only for canvas nodes

    class GraphEdge(TypedDict, total=False):
        """An edge in the knowledge graph.

        NOTE: 'from' is a Python reserved word; stored under key "from" in JSON.
        total=False: canvas field only present for canvas edges.
        """
        type: str
        canvas: str        # only for canvas edges

    class KnowledgeGraph(TypedDict):
        """The knowledge graph: nodes + edges."""
        nodes: list
        edges: list

    class IndexManifest(TypedDict, total=False):
        """Manifest written to manifest.json.

        total=False: the 'files' dict may not be present on older manifests.
        """
        index_version: int
        generated_at: str
        generated_epoch: float
        page_count: int
        raw_count: int
        task_doc_count: int
        link_count: int
        search_docs: int
        graph_nodes: int
        graph_edges: int
        files: dict

    class LinkIndex(TypedDict):
        """Output of build_link_index()."""
        nodes: list
        edges: list
        backlinks: dict
        missing: dict

    class SourceIndex(TypedDict, total=False):
        """Output of build_source_index().

        total=False: some diagnostic lists may be empty and callers use .get().
        """
        raw: list
        pages: dict
        raw_to_pages: dict
        source_summaries: dict
        raw_without_summary: list
        summary_without_raw: list
        missing_sources: list

else:
    # Fallback: plain dict aliases so runtime doesn't break if TypedDict is missing.
    PageRecord = dict  # type: ignore[misc,assignment]
    RawRecord = dict  # type: ignore[misc,assignment]
    SearchDoc = dict  # type: ignore[misc,assignment]
    WikiNode = dict  # type: ignore[misc,assignment]
    GraphEdge = dict  # type: ignore[misc,assignment]
    KnowledgeGraph = dict  # type: ignore[misc,assignment]
    IndexManifest = dict  # type: ignore[misc,assignment]
    LinkIndex = dict  # type: ignore[misc,assignment]
    SourceIndex = dict  # type: ignore[misc,assignment]


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def index_dir(brain: Path) -> Path:
    return brain / INDEX_DIR


def relpath(brain: Path, path: Path) -> str:
    return str(path.relative_to(brain))


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    brain_wiki.write_text(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def tokenize(text: str) -> list:
    return re.findall(r"[\w-]+", text.lower(), flags=re.UNICODE)


def now_epoch() -> float:
    return _dt.datetime.now(_dt.timezone.utc).timestamp()


def iter_indexed_files(brain: Path) -> list:
    files = []
    files.extend(wiki_page_paths(brain))
    files.extend(raw_paths(brain))
    files.extend(task_paths(brain))
    return files


def file_mtimes(brain: Path) -> dict:
    return {relpath(brain, path): path.stat().st_mtime for path in iter_indexed_files(brain)}


def wiki_page_paths(brain: Path) -> list:
    wiki = brain / "wiki"
    if not wiki.exists():
        return []
    return sorted(
        path
        for path in wiki.glob("*.md")
        if path.is_file() and path.stem not in brain_wiki.INDEX_EXCLUDED
    )


def raw_paths(brain: Path) -> list:
    raw = brain / "raw"
    if not raw.exists():
        return []
    return sorted(path for path in raw.glob("*.md") if path.is_file())


def task_paths(brain: Path) -> list:
    tasks = brain / "tasks"
    if not tasks.exists():
        return []
    return sorted(path for path in tasks.glob("*.md") if path.is_file())


# ---------------------------------------------------------------------------
# Record builders
# ---------------------------------------------------------------------------

def page_record(brain: Path, path: Path, all_slugs: set) -> dict:
    text = brain_wiki.read_text(path)
    fm, body = brain_wiki.parse_frontmatter(text)
    links = sorted(set(brain_wiki.extract_wikilinks(body)))
    return {
        "slug": path.stem,
        "path": relpath(brain, path),
        "title": str(fm.get("title") or path.stem),
        "type": str(fm.get("type") or "concept"),
        "tags": brain_wiki.as_list(fm.get("tags")),
        "created": str(fm.get("created") or ""),
        "updated": str(fm.get("updated") or ""),
        "curation": str(fm.get("curation") or "agent"),
        "protected": brain_wiki.as_bool(fm.get("protected")),
        "source_policy": str(fm.get("source_policy") or "advisory"),
        "sources": brain_wiki.source_refs(fm),
        "related": brain_wiki.as_list(fm.get("related")),
        "implements": brain_wiki.as_list(fm.get("implements")),
        "refutes": brain_wiki.as_list(fm.get("refutes")),
        "depends_on": brain_wiki.as_list(fm.get("depends_on")),
        "links": links,
        "missing_links": sorted(link for link in links if link not in all_slugs),
        "word_count": len(tokenize(body)),
        "mtime": path.stat().st_mtime,
    }


def raw_record(brain: Path, path: Path) -> dict:
    text = brain_wiki.read_text(path)
    fm, body = brain_wiki.parse_frontmatter(text)
    return {
        "slug": path.stem,
        "path": relpath(brain, path),
        "title": str(fm.get("title") or path.stem),
        "type": str(fm.get("type") or ""),
        "url": str(fm.get("url") or ""),
        "fetched": str(fm.get("fetched") or ""),
        "word_count": len(tokenize(body)),
        "mtime": path.stat().st_mtime,
    }


# ---------------------------------------------------------------------------
# Unified search_doc builder (replaces search_doc_from_page/raw/task)
# ---------------------------------------------------------------------------

def search_doc(
    brain: Path,
    path: Path,
    kind: str,
    record: dict = None,
) -> dict:
    """Build a SearchDoc for the BM25 corpus.

    Unifies the three former helpers search_doc_from_page(), search_doc_from_raw(),
    and search_doc_from_task(), which differed only in 'kind' and 'id' derivation.

    Args:
        brain:  Brain root path.
        path:   Absolute path to the source file.
        kind:   "wiki" | "raw" | "task"
        record: Pre-built page_record or raw_record dict; omit for tasks (kind="task"),
                where text is read directly and id is derived from the stem.
    """
    if kind == "wiki":
        _fm, body = brain_wiki.parse_frontmatter(brain_wiki.read_text(path))
        return {
            "id": record["slug"],
            "path": record["path"],
            "kind": "wiki",
            "page_type": record["type"],
            "title": record["title"],
            "text": "{}\n{}".format(record["title"], body),
            "mtime": record["mtime"],
        }
    elif kind == "raw":
        _fm, body = brain_wiki.parse_frontmatter(brain_wiki.read_text(path))
        return {
            "id": "raw/{}".format(record["slug"]),
            "path": record["path"],
            "kind": "raw",
            "page_type": "raw",
            "title": record["title"],
            "text": "{}\n{}".format(record["title"], body),
            "mtime": record["mtime"],
        }
    else:  # task
        return {
            "id": "tasks/{}".format(path.stem),
            "path": relpath(brain, path),
            "kind": "task",
            "page_type": "task",
            "title": "Tasks: {}".format(path.stem),
            "text": brain_wiki.read_text(path),
            "mtime": path.stat().st_mtime,
        }


# ---------------------------------------------------------------------------
# Index builders
# ---------------------------------------------------------------------------

def build_link_index(page_records: list) -> dict:
    nodes = sorted(record["slug"] for record in page_records)
    node_set = set(nodes)
    edges = []
    backlinks = defaultdict(list)
    missing = defaultdict(list)
    for record in page_records:
        for target in record["links"]:
            edge = {"from": record["slug"], "to": target, "exists": target in node_set}
            edges.append(edge)
            if target in node_set:
                backlinks[target].append(record["slug"])
            else:
                missing[record["slug"]].append(target)
    return {
        "nodes": nodes,
        "edges": sorted(edges, key=lambda item: (item["from"], item["to"])),
        "backlinks": {key: sorted(set(value)) for key, value in sorted(backlinks.items())},
        "missing": {key: sorted(set(value)) for key, value in sorted(missing.items())},
    }


def build_source_index(page_records: list, raw_records: list) -> dict:
    raw_by_path = {record["path"]: record for record in raw_records}
    raw_by_slug = {record["slug"]: record for record in raw_records}
    page_sources = {}
    raw_to_pages = defaultdict(list)
    source_summaries = {}
    summary_without_raw = []

    for record in page_records:
        sources = record["sources"]
        if sources:
            page_sources[record["slug"]] = sources
        for source in sources:
            source_path = brain_wiki.raw_ref_to_path(Path("."), source)
            normalized = str(source_path)
            if normalized.startswith("raw/"):
                raw_ref = normalized
            else:
                raw_ref = "raw/{}.md".format(Path(source).stem)
            raw_to_pages[raw_ref].append(record["slug"])
        if record["type"] == "source-summary":
            if sources:
                source_summaries[sources[0]] = record["slug"]
            else:
                summary_without_raw.append(record["slug"])

    normalized_summary_keys = {
        key if str(key).startswith("raw/") else "raw/{}.md".format(Path(str(key)).stem): value
        for key, value in source_summaries.items()
    }
    raw_without_summary = []
    for raw_path in sorted(raw_by_path):
        if raw_path not in normalized_summary_keys:
            raw_without_summary.append(raw_path)

    missing_sources = []
    for page, sources in page_sources.items():
        for source in sources:
            if str(source).startswith("raw/"):
                raw_ref = str(source)
            else:
                raw_ref = "raw/{}.md".format(Path(str(source)).stem)
            if raw_ref not in raw_by_path and Path(raw_ref).stem not in raw_by_slug:
                missing_sources.append({"page": page, "source": source})

    return {
        "raw": raw_records,
        "pages": page_sources,
        "raw_to_pages": {key: sorted(set(value)) for key, value in sorted(raw_to_pages.items())},
        "source_summaries": normalized_summary_keys,
        "raw_without_summary": raw_without_summary,
        "summary_without_raw": summary_without_raw,
        "missing_sources": missing_sources,
    }


def build_knowledge_graph(brain: Path, page_records: list) -> dict:
    nodes = []
    edges = []
    # Dedup edges: each (from, to, type) tuple only once
    seen_edges = set()

    def _add_edge(from_id, to_id, edge_type, **extra):
        key = (from_id, to_id, edge_type)
        if key not in seen_edges:
            seen_edges.add(key)
            entry = {"from": from_id, "to": to_id, "type": edge_type}
            entry.update(extra)
            edges.append(entry)

    # 1. Wiki nodes and edges
    for record in page_records:
        slug = record["slug"]
        nodes.append({"id": slug, "type": "wiki", "title": record["title"]})

        for link in record.get("links", []):
            _add_edge(slug, link, "relates_to")
        for rel in record.get("related", []):
            _add_edge(slug, rel, "relates_to")
        for imp in record.get("implements", []):
            _add_edge(slug, imp, "implements")
        for ref in record.get("refutes", []):
            _add_edge(slug, ref, "refutes")
        for dep in record.get("depends_on", []):
            _add_edge(slug, dep, "depends_on")

    # 2. Task nodes and edges
    tasks = brain_tasks.load_active(brain) + brain_tasks.load_done(brain)
    for task in tasks:
        tid = task["id"]
        nodes.append({"id": tid, "type": "task", "title": task["title"]})
        if task.get("parent"):
            _add_edge(tid, task["parent"], "parent")
        for dep in task.get("depends_on", []):
            _add_edge(tid, dep, "depends_on")

    # 3. Canvas files
    wiki = brain / "wiki"
    if wiki.exists():
        for canvas_path in wiki.glob("*.canvas"):
            try:
                canvas_data = json.loads(canvas_path.read_text(encoding="utf-8"))
                for node in canvas_data.get("nodes", []):
                    nid = node.get("id")
                    if not nid:
                        continue
                    node_type = "canvas_text" if node.get("type") == "text" else "canvas_file"
                    title = node.get("text") or node.get("file") or nid
                    nodes.append({"id": nid, "type": node_type, "title": title, "canvas": canvas_path.stem})
                for edge in canvas_data.get("edges", []):
                    from_node = edge.get("fromNode")
                    to_node = edge.get("toNode")
                    if not from_node or not to_node:
                        continue
                    edge_type = edge.get("label") or "canvas_edge"
                    _add_edge(from_node, to_node, edge_type, canvas=canvas_path.stem)
            except (json.JSONDecodeError, OSError) as e:
                sys.stderr.write("warning: skipping canvas {}: {}\n".format(canvas_path.name, e))

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# rebuild_index helpers (SRP decomposition)
# ---------------------------------------------------------------------------

def _collect_records(brain):
    """Collect all page, raw, and task records from disk.

    Returns:
        (page_records, raw_records, page_paths, task_file_paths, all_slugs)
    """
    page_paths = wiki_page_paths(brain)
    all_slugs = {path.stem for path in page_paths}
    page_records = [page_record(brain, path, all_slugs) for path in page_paths]
    raw_records = [raw_record(brain, path) for path in raw_paths(brain)]
    t_paths = task_paths(brain)
    return page_records, raw_records, page_paths, t_paths, all_slugs


def _build_search_corpus(brain, page_records, raw_records, page_paths, t_paths):
    """Build the BM25 search corpus from page, raw, and task documents."""
    docs = []
    page_by_path = {record["path"]: record for record in page_records}
    raw_by_path = {record["path"]: record for record in raw_records}

    for path in page_paths:
        docs.append(search_doc(brain, path, "wiki", page_by_path[relpath(brain, path)]))
    for path in raw_paths(brain):
        docs.append(search_doc(brain, path, "raw", raw_by_path[relpath(brain, path)]))
    for path in t_paths:
        docs.append(search_doc(brain, path, "task"))

    return docs


def _compose_manifest(brain, page_records, raw_records, t_paths, link_index, search_docs, graph, generated_epoch):
    """Compose the index manifest dict."""
    generated_at = _dt.datetime.fromtimestamp(generated_epoch, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "index_version": INDEX_VERSION,
        "generated_at": generated_at,
        "generated_epoch": generated_epoch,
        "page_count": len(page_records),
        "raw_count": len(raw_records),
        "task_doc_count": len(t_paths),
        "link_count": len(link_index["edges"]),
        "search_docs": len(search_docs),
        "graph_nodes": len(graph["nodes"]),
        "graph_edges": len(graph["edges"]),
        "files": file_mtimes(brain),
    }


def _write_artifacts(out, manifest, page_records, link_index, source_index, graph, search_docs):
    """Write all 6 index artifacts to disk."""
    generated_at = manifest["generated_at"]
    write_json(out / "pages.json", {"generated_at": generated_at, "pages": page_records})
    write_json(out / "links.json", {"generated_at": generated_at, **link_index})
    write_json(out / "sources.json", {"generated_at": generated_at, **source_index})
    write_json(out / "graph.json", {"generated_at": generated_at, **graph})
    with (out / "search.jsonl").open("w", encoding="utf-8") as handle:
        for doc in search_docs:
            handle.write(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n")
    write_json(out / "manifest.json", manifest)


# ---------------------------------------------------------------------------
# rebuild_index — orchestrator (~15 lines of logic)
# ---------------------------------------------------------------------------

def rebuild_index(brain_value=None, with_obsidian: bool = False) -> dict:
    brain = brain_wiki.brain_path(str(brain_value) if brain_value else None)
    out = index_dir(brain)
    out.mkdir(parents=True, exist_ok=True)

    page_records, raw_records, page_paths, t_paths, _slugs = _collect_records(brain)
    link_index = build_link_index(page_records)
    source_index = build_source_index(page_records, raw_records)
    search_docs = _build_search_corpus(brain, page_records, raw_records, page_paths, t_paths)
    graph = build_knowledge_graph(brain, page_records)

    manifest = _compose_manifest(
        brain, page_records, raw_records, t_paths,
        link_index, search_docs, graph, now_epoch()
    )
    _write_artifacts(out, manifest, page_records, link_index, source_index, graph, search_docs)

    if with_obsidian:
        export_obsidian(brain)
    return manifest


# ---------------------------------------------------------------------------
# Search / query helpers
# ---------------------------------------------------------------------------

def load_search_docs(brain: Path) -> list:
    search_file = index_dir(brain) / "search.jsonl"
    if not search_file.exists():
        return []
    docs = []
    with search_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    return docs


class BM25:
    def __init__(self, docs: list, k1: float = 1.5, b: float = 0.75):
        self.docs = docs
        self.k1 = k1
        self.b = b
        self.doc_count = len(docs)
        self.avgdl = sum(len(doc) for doc in docs) / self.doc_count if self.doc_count else 0.0
        self.doc_freqs = Counter()
        for doc in docs:
            self.doc_freqs.update(set(doc))

    def idf(self, term: str) -> float:
        freq = self.doc_freqs.get(term, 0)
        return math.log((self.doc_count - freq + 0.5) / (freq + 0.5) + 1.0)

    def score(self, query: list, doc: list) -> float:
        if not query or not doc or not self.avgdl:
            return 0.0
        counts = Counter(doc)
        score = 0.0
        for term in query:
            tf = counts.get(term, 0)
            if not tf:
                continue
            denom = tf + self.k1 * (1.0 - self.b + self.b * len(doc) / self.avgdl)
            score += self.idf(term) * (tf * (self.k1 + 1.0)) / denom
        return score


def snippet_for(text: str, query_terms: list, size: int = 180) -> str:
    lowered = text.lower()
    positions = [lowered.find(term) for term in query_terms if lowered.find(term) >= 0]
    idx = min(positions) if positions else 0
    start = max(0, idx - 60)
    end = min(len(text), start + size)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def search_brain(
    brain_value,
    query: str,
    page_type: str = "",
    limit: int = 10,
) -> list:
    brain = brain_wiki.brain_path(str(brain_value) if brain_value else None)
    docs = load_search_docs(brain)
    if page_type:
        docs = [doc for doc in docs if doc.get("page_type") == page_type or doc.get("kind") == page_type]
    tokens = [tokenize(doc.get("text", "")) for doc in docs]
    bm25 = BM25(tokens)
    query_terms = tokenize(query)
    scored = []
    for doc, doc_tokens in zip(docs, tokens):
        score = bm25.score(query_terms, doc_tokens)
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "score": round(score, 4),
            "id": doc["id"],
            "path": doc["path"],
            "kind": doc["kind"],
            "page_type": doc["page_type"],
            "title": doc["title"],
            "snippet": snippet_for(doc.get("text", ""), query_terms),
        }
        for score, doc in scored[:limit]
    ]


def get_page(brain_value, slug: str):
    brain = brain_wiki.brain_path(str(brain_value) if brain_value else None)
    data = load_json(index_dir(brain) / "pages.json", {"pages": []})
    for page in data.get("pages", []):
        if page.get("slug") == slug:
            return page
    return None


def get_backlinks(brain_value, slug: str) -> list:
    brain = brain_wiki.brain_path(str(brain_value) if brain_value else None)
    data = load_json(index_dir(brain) / "links.json", {"backlinks": {}})
    return data.get("backlinks", {}).get(slug, [])


def get_source_map(brain_value, slug: str = "") -> dict:
    brain = brain_wiki.brain_path(str(brain_value) if brain_value else None)
    data = load_json(index_dir(brain) / "sources.json", {})
    if not slug:
        return data
    raw_ref = slug if slug.startswith("raw/") else "raw/{}.md".format(Path(slug).stem)
    return {
        "raw": raw_ref,
        "pages": data.get("raw_to_pages", {}).get(raw_ref, []),
        "summary": data.get("source_summaries", {}).get(raw_ref, ""),
    }


def stale_status(brain_value=None) -> dict:
    brain = brain_wiki.brain_path(str(brain_value) if brain_value else None)
    manifest = load_json(index_dir(brain) / "manifest.json", None)
    if not manifest:
        return {"status": "missing", "stale": True, "stale_files": []}
    indexed = manifest.get("files", {})
    current = file_mtimes(brain)
    stale_files = []
    for path, mtime in current.items():
        if path not in indexed or float(indexed[path]) < float(mtime):
            stale_files.append(path)
    removed_files = sorted(path for path in indexed if path not in current)
    stale = bool(stale_files or removed_files)
    return {
        "status": "stale" if stale else "ok",
        "stale": stale,
        "stale_files": sorted(stale_files),
        "removed_files": removed_files,
    }


def index_status(brain_value=None) -> dict:
    brain = brain_wiki.brain_path(str(brain_value) if brain_value else None)
    manifest = load_json(index_dir(brain) / "manifest.json", None)
    if not manifest:
        return {"status": "missing", "health": "missing", "stale": True, "stale_files": []}
    stale = stale_status(brain)
    return {
        **manifest,
        "status": stale["status"],
        "health": stale["status"],
        "stale": stale["stale"],
        "stale_files": stale["stale_files"],
        "removed_files": stale["removed_files"],
    }


# ---------------------------------------------------------------------------
# Obsidian export
# ---------------------------------------------------------------------------

def _canvas_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def export_obsidian(brain_value=None) -> dict:
    brain = brain_wiki.brain_path(str(brain_value) if brain_value else None)
    views = brain / "wiki" / "_views"
    views.mkdir(parents=True, exist_ok=True)

    pages_base = """# Generated by brain-index export-obsidian
filters:
  and:
    - 'file.path.startsWith("wiki/")'
views:
  - type: table
    name: Pages
    order:
      - file.name
      - title
      - type
      - updated
      - curation
      - source_policy
"""
    sources_base = """# Generated by brain-index export-obsidian
filters:
  and:
    - 'type == "source-summary"'
views:
  - type: table
    name: Sources
    order:
      - file.name
      - title
      - sources
      - updated
"""
    decisions_base = """# Generated by brain-index export-obsidian
filters:
  and:
    - 'type == "decision"'
views:
  - type: table
    name: Decisions
    order:
      - file.name
      - title
      - updated
      - sources
"""
    tasks_base = """# Generated by brain-index export-obsidian
filters:
  or:
    - 'file.path == "tasks/active.md"'
    - 'file.path == "tasks/done.md"'
views:
  - type: table
    name: Task Queue
    order:
      - file.name
      - file.mtime
      - file.size
"""
    brain_wiki.write_text(views / "brain-pages.base", pages_base)
    brain_wiki.write_text(views / "brain-sources.base", sources_base)
    brain_wiki.write_text(views / "brain-decisions.base", decisions_base)
    brain_wiki.write_text(views / "brain-tasks.base", tasks_base)

    pages_data = load_json(index_dir(brain) / "pages.json", {"pages": []}).get("pages", [])
    links_data = load_json(index_dir(brain) / "links.json", {"edges": []})
    nodes = []
    node_ids = {}
    for idx, page in enumerate(pages_data):
        slug = page["slug"]
        node_id = _canvas_id(slug)
        node_ids[slug] = node_id
        nodes.append({
            "id": node_id,
            "type": "file",
            "file": "{}.md".format(slug),
            "x": (idx % 5) * 360,
            "y": (idx // 5) * 260,
            "width": 300,
            "height": 180,
        })
    edges = []
    for edge in links_data.get("edges", []):
        if not edge.get("exists"):
            continue
        if edge["from"] not in node_ids or edge["to"] not in node_ids:
            continue
        edges.append({
            "id": _canvas_id("{}->{}".format(edge["from"], edge["to"])),
            "fromNode": node_ids[edge["from"]],
            "toNode": node_ids[edge["to"]],
        })
    brain_wiki.write_text(
        views / "link-graph.canvas",
        json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, indent=2) + "\n",
    )
    return {
        "pages": str((views / "brain-pages.base").relative_to(brain)),
        "sources": str((views / "brain-sources.base").relative_to(brain)),
        "decisions": str((views / "brain-decisions.base").relative_to(brain)),
        "tasks": str((views / "brain-tasks.base").relative_to(brain)),
        "canvas": str((views / "link-graph.canvas").relative_to(brain)),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["rebuild", "status"])
    args = parser.parse_args()
    if args.command == "rebuild":
        print(json.dumps(rebuild_index(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(index_status(), ensure_ascii=False, indent=2))
