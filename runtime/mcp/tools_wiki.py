import re
from common import mcp, BRAIN, append_log, git_commit, brain_wiki, brain_index
from result import ok, error

@mcp.tool()
def get_memory() -> dict:
    """Read MEMORY.md — the system schema."""
    f = BRAIN / "MEMORY.md"
    return {"content": f.read_text() if f.exists() else ""}

@mcp.tool()
def get_role(role: str) -> dict:
    """Read a role definition."""
    f = BRAIN / "roles" / f"{role}.md"
    if not f.exists():
        return error(f"no role {role}")
    return {"content": f.read_text()}

@mcp.tool()
def list_roles() -> dict:
    """List all available roles."""
    rdir = BRAIN / "roles"
    if not rdir.exists():
        return {"roles": []}
    return {"roles": sorted(f.stem for f in rdir.glob("*.md"))}

@mcp.tool()
def list_teams() -> dict:
    """List teams (named role groups for council)."""
    tdir = BRAIN / "teams"
    if not tdir.exists():
        return {"teams": {}}
    out = {}
    for f in tdir.glob("*.md"):
        text = f.read_text()
        if m := re.search(r"^roles:\s*\[([^\]]*)\]", text, re.M):
            out[f.stem] = [r.strip() for r in m.group(1).split(",") if r.strip()]
    return {"teams": out}

@mcp.tool()
def get_doctrine(name: str = "") -> dict:
    """Read a doctrine document or list all."""
    ddir = BRAIN / "doctrine"
    if not ddir.exists():
        return {"doctrines": []}
    if not name:
        return {"doctrines": sorted(f.stem for f in ddir.glob("*.md"))}
    f = ddir / f"{name}.md"
    if not f.exists():
        return error(f"no doctrine {name}")
    return {"content": f.read_text()}

@mcp.tool()
def search_wiki(query: str, max_results: int = 10) -> dict:
    """Naive keyword search across wiki/. Returns matching pages with snippets."""
    wdir = BRAIN / "wiki"
    if not wdir.exists():
        return {"results": []}
    q = query.lower()
    hits = []
    for f in wdir.rglob("*.md"):
        text = f.read_text(errors="replace")
        tl = text.lower()
        if q in tl or q in f.stem.lower():
            idx = tl.find(q)
            snippet = text[max(0, idx - 80):idx + 200] if idx >= 0 else text[:200]
            hits.append({"path": str(f.relative_to(BRAIN)), "title": f.stem,
                         "snippet": snippet})
            if len(hits) >= max_results:
                break
    return {"results": hits, "count": len(hits)}

@mcp.tool()
def read_wiki_page(path: str) -> dict:
    """Read a wiki page. Path can be relative to brain (wiki/foo.md) or just slug."""
    p = BRAIN / path if "/" in path else BRAIN / "wiki" / f"{path}.md"
    if not p.exists():
        return error(f"no page at {p}")
    return {"content": p.read_text(), "path": str(p.relative_to(BRAIN))}

@mcp.tool()
def write_wiki_page(slug: str, content: str, page_type: str = "concept",
                    tags: list[str] = None, sources: list[str] = None,
                    related: list[str] = None, title: str = "",
                    curation: str = "agent", protected: bool = False,
                    source_policy: str = "", force: bool = False,
                    update_index: bool = False) -> dict:
    """Create or overwrite a wiki page with frontmatter validation."""
    try:
        p = brain_wiki.write_wiki_page(
            BRAIN, slug, content, page_type=page_type, title=title or slug,
            tags=tags or [], sources=sources or [], related=related or [],
            curation=curation, protected=protected, source_policy=source_policy or None,
            force=force, update_index=update_index,
        )
    except (ValueError, FileNotFoundError, PermissionError) as exc:
        return error(str(exc))
    append_log("wiki-update", "", "", f"page={slug}")
    git_commit(f"wiki: {slug}", f"wiki/{slug}.md", "wiki/index.md", "wiki/log.md")
    return ok(path=str(p.relative_to(BRAIN)))

@mcp.tool()
def append_wiki_log(operation: str, task_id: str = "", agent_id: str = "",
                    message: str = "") -> dict:
    """Append a custom entry to wiki/log.md."""
    append_log(operation, task_id, agent_id, message)
    return ok()

@mcp.tool()
def validate_wiki() -> dict:
    """Validate wiki/raw/task references and return structured issues."""
    issues = brain_wiki.validate_all(BRAIN)
    return {
        "status": "error" if any(i.severity == "ERROR" for i in issues) else "ok",
        "issues": [i.__dict__ for i in issues],
        "errors": sum(1 for i in issues if i.severity == "ERROR"),
        "warnings": sum(1 for i in issues if i.severity == "WARN"),
    }

@mcp.tool()
def lint_wiki(fix_index: bool = False) -> dict:
    """Lint wiki hygiene. If fix_index is true, regenerate wiki/index.md."""
    index_path = ""
    if fix_index:
        index_path = str(brain_wiki.render_index(BRAIN).relative_to(BRAIN))
        append_log("lint", "", "", "fix-index")
        git_commit("wiki: regenerate index", "wiki/index.md", "wiki/log.md")
    issues = brain_wiki.lint_wiki(BRAIN)
    return {
        "status": "error" if any(i.severity == "ERROR" for i in issues) else "ok",
        "index_path": index_path,
        "issues": [i.__dict__ for i in issues],
        "errors": sum(1 for i in issues if i.severity == "ERROR"),
        "warnings": sum(1 for i in issues if i.severity == "WARN"),
    }

@mcp.tool()
def regenerate_wiki_index() -> dict:
    """Regenerate wiki/index.md from wiki page frontmatter."""
    path = brain_wiki.render_index(BRAIN)
    append_log("lint", "", "", "fix-index")
    git_commit("wiki: regenerate index", "wiki/index.md", "wiki/log.md")
    return ok(path=str(path.relative_to(BRAIN)))
