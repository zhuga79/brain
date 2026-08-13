from common import mcp, BRAIN, append_log, git_commit, brain_index
from result import ok, error

@mcp.tool()
def add_raw_source(slug: str, content: str, title: str = "",
                   url: str = "", source_type: str = "article",
                   force: bool = False) -> dict:
    """Add a source to raw/ with metadata frontmatter."""
    from common import brain_wiki
    normalized = brain_wiki.normalize_slug(slug)
    try:
        p = brain_wiki.write_raw_source(
            BRAIN, normalized, content, title=title, url=url, source_type=source_type, force=force,
        )
    except (FileExistsError, ValueError) as exc:
        return error(str(exc))
    append_log("ingest", "", "", f"raw/{normalized}.md")
    git_commit(f"raw: {normalized}")
    return ok(path=str(p.relative_to(BRAIN)))

@mcp.tool()
def ingest_source(slug: str, content: str, title: str = "",
                  url: str = "", source_type: str = "article",
                  update_index: bool = True) -> dict:
    """Ingest raw source and create source-summary skeleton if absent."""
    from common import brain_wiki
    normalized = brain_wiki.normalize_slug(slug or title)
    raw_result = add_raw_source(normalized, content, title, url, source_type, False)
    if raw_result.get("error"):
        return raw_result

    summary_slug = f"source-{normalized}"
    summary_path = BRAIN / "wiki" / f"{summary_slug}.md"
    summary_created = False
    if not summary_path.exists():
        body = "\n".join([
            f"# Source: {title or normalized}", "",
            f"- Raw source: `raw/{normalized}.md`", f"- URL: {url or 'n/a'}", "",
            "## Summary", "TODO: summarize the source.", "",
            "## Extracted Claims", "- TODO", "",
        ])
        try:
            brain_wiki.write_wiki_page(
                BRAIN, summary_slug, body, page_type="source-summary",
                title=f"Source: {title or normalized}", tags=["source"],
                sources=[f"raw/{normalized}.md"], curation="agent",
                protected=False, source_policy="required", update_index=update_index,
            )
            summary_created = True
        except Exception as exc:
            return error(f"raw source written but source-summary failed: {exc}")
    elif update_index:
        brain_wiki.render_index(BRAIN)

    append_log("ingest", "", "", f"summary=wiki/{summary_slug}.md")
    git_commit(f"ingest: {normalized}")
    return ok(
        raw_path=raw_result["path"],
        summary_path=str(summary_path.relative_to(BRAIN)),
        summary_created=summary_created,
    )

@mcp.tool()
def rebuild_index(with_obsidian: bool = False) -> dict:
    """Rebuild the machine index (BM25, backlinks, etc.)."""
    try:
        manifest = brain_index.rebuild_index(BRAIN, with_obsidian=with_obsidian)
        append_log("index-rebuild", "", "", f"pages={manifest.get('page_count')}")
        if with_obsidian:
            git_commit("index: export obsidian views")
        return ok(manifest=manifest)
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def index_status() -> dict:
    """Get the status of the brain index."""
    return brain_index.index_status(BRAIN)

@mcp.tool()
def search_brain(query: str, page_type: str = "", limit: int = 10) -> dict:
    """Full-text search in the brain using BM25."""
    results = brain_index.search_brain(BRAIN, query, page_type=page_type, limit=limit)
    return {"results": results, "count": len(results)}

@mcp.tool()
def get_backlinks(slug: str) -> dict:
    """Get all pages that link to the given slug."""
    backlinks = brain_index.get_backlinks(BRAIN, slug)
    return {"backlinks": backlinks, "count": len(backlinks)}

@mcp.tool()
def get_source_map(slug: str = "") -> dict:
    """Get the map of wiki pages to their raw sources."""
    source_map = brain_index.get_source_map(BRAIN, slug)
    return {"source_map": source_map}

@mcp.tool()
def vector_status() -> dict:
    """Return the status of the optional vector index (chromadb)."""
    from tools_misc import _run_brain_vector
    return _run_brain_vector(["status"])

@mcp.tool()
def vector_search(query: str, top_k: int = 5) -> dict:
    """Semantic vector search over Brain wiki (requires chromadb)."""
    from tools_misc import _run_brain_vector
    return _run_brain_vector(["search", query, "--top-k", str(top_k)])
