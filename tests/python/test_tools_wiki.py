import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

def _make_fastmcp_mock():
    mock = MagicMock()
    mock.tool.return_value = lambda f: f
    return mock

@pytest.fixture
def tw(tmp_path, monkeypatch):
    """temp_brain: isolated BRAIN_PATH with minimal structure, reloaded modules."""
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))

    (tmp_path / "wiki").mkdir()
    (tmp_path / "roles").mkdir()
    (tmp_path / "teams").mkdir()
    (tmp_path / "doctrine").mkdir()
    (tmp_path / "wiki" / "log.md").write_text("# Log\n\n")

    # Fake packages
    fake_mcp_pkg = types.ModuleType("mcp")
    fake_mcp_server = types.ModuleType("mcp.server")
    fake_mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")
    fake_mcp_fastmcp.FastMCP = lambda *a, **k: _make_fastmcp_mock()
    fake_mcp_pkg.server = fake_mcp_server
    fake_mcp_server.fastmcp = fake_mcp_fastmcp
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp_pkg)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_mcp_server)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_mcp_fastmcp)

    # Force reload
    for mod_name in ["common", "tools_wiki"]:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    import common
    mock_wiki = MagicMock()
    monkeypatch.setattr(common, "brain_wiki", mock_wiki)
    
    import tools_wiki as w

    # Sync globals
    monkeypatch.setattr(common, "BRAIN", tmp_path)
    monkeypatch.setattr(w, "BRAIN", tmp_path, raising=False)
    
    monkeypatch.setattr(common, "git_commit", lambda *a, **k: None)
    monkeypatch.setattr(w, "git_commit", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(common, "append_log", lambda *a, **k: None)
    monkeypatch.setattr(w, "append_log", lambda *a, **k: None, raising=False)

    yield w, tmp_path, common, mock_wiki

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_get_memory(tw):
    w, tmp, common, _ = tw
    (tmp / "MEMORY.md").write_text("MEM CONTENT")
    res = w.get_memory()
    assert res["content"] == "MEM CONTENT"

def test_get_role(tw):
    w, tmp, common, _ = tw
    (tmp / "roles" / "dev.md").write_text("ROLE CONTENT")
    res = w.get_role("dev")
    assert res["content"] == "ROLE CONTENT"
    assert w.get_role("missing")["status"] == "error"

def test_list_roles(tw):
    w, tmp, common, _ = tw
    (tmp / "roles" / "r1.md").write_text("...")
    (tmp / "roles" / "r2.md").write_text("...")
    res = w.list_roles()
    assert res["roles"] == ["r1", "r2"]

def test_list_teams(tw):
    w, tmp, common, _ = tw
    (tmp / "teams" / "t1.md").write_text("roles: [r1, r2]")
    res = w.list_teams()
    assert res["teams"]["t1"] == ["r1", "r2"]

def test_get_doctrine(tw):
    w, tmp, common, _ = tw
    (tmp / "doctrine" / "d1.md").write_text("DOC CONTENT")
    # List
    assert w.get_doctrine()["doctrines"] == ["d1"]
    # Read
    assert w.get_doctrine("d1")["content"] == "DOC CONTENT"

def test_search_wiki(tw):
    w, tmp, common, _ = tw
    (tmp / "wiki" / "p1.md").write_text("keyword here")
    res = w.search_wiki("keyword")
    assert res["count"] == 1
    assert res["results"][0]["title"] == "p1"

def test_read_wiki_page(tw):
    w, tmp, common, _ = tw
    (tmp / "wiki" / "p1.md").write_text("content")
    res = w.read_wiki_page("p1")
    assert res["content"] == "content"
    
    res2 = w.read_wiki_page("wiki/p1.md")
    assert res2["content"] == "content"

def test_write_wiki_page(tw):
    w, tmp, common, mock_wiki = tw
    mock_wiki.write_wiki_page.return_value = tmp / "wiki" / "slug.md"
    
    res = w.write_wiki_page("slug", "content")
    assert res["status"] == "ok"
    assert res["path"] == "wiki/slug.md"
    mock_wiki.write_wiki_page.assert_called_once()

def test_validate_and_lint(tw):
    w, tmp, common, mock_wiki = tw
    
    class SimpleIssue:
        def __init__(self, severity):
            self.severity = severity
    
    issue = SimpleIssue("ERROR")
    mock_wiki.validate_all.return_value = [issue]
    mock_wiki.lint_wiki.return_value = []
    
    assert w.validate_wiki()["status"] == "error"
    assert w.lint_wiki()["status"] == "ok"

def test_regenerate_index(tw):
    w, tmp, common, mock_wiki = tw
    mock_wiki.render_index.return_value = tmp / "wiki" / "index.md"
    res = w.regenerate_wiki_index()
    assert res["status"] == "ok"
    assert res["path"] == "wiki/index.md"
