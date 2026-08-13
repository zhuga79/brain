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
def ti(tmp_path, monkeypatch):
    """temp_brain: isolated BRAIN_PATH with minimal structure, reloaded modules."""
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))

    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
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
    for mod_name in ["common", "tools_index"]:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    import common
    
    # Mock brain_wiki and brain_index in common
    mock_wiki = MagicMock()
    mock_index = MagicMock()
    monkeypatch.setattr(common, "brain_wiki", mock_wiki)
    monkeypatch.setattr(common, "brain_index", mock_index)
    
    import tools_index as i

    # Sync globals
    monkeypatch.setattr(common, "BRAIN", tmp_path)
    monkeypatch.setattr(i, "BRAIN", tmp_path, raising=False)
    monkeypatch.setattr(i, "brain_index", mock_index, raising=False)
    
    monkeypatch.setattr(common, "git_commit", lambda *a, **k: None)
    monkeypatch.setattr(i, "git_commit", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(common, "append_log", lambda *a, **k: None)
    monkeypatch.setattr(i, "append_log", lambda *a, **k: None, raising=False)

    yield i, tmp_path, common, mock_wiki, mock_index

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_add_raw_source(ti):
    i, tmp, common, mock_wiki, _ = ti
    mock_wiki.normalize_slug.return_value = "test-slug"
    mock_wiki.write_raw_source.return_value = tmp / "raw" / "test-slug.md"
    
    res = i.add_raw_source("Test Slug", "content")
    assert res["status"] == "ok"
    assert res["path"] == "raw/test-slug.md"
    mock_wiki.write_raw_source.assert_called_once()

def test_add_raw_source_error(ti):
    i, tmp, common, mock_wiki, _ = ti
    mock_wiki.normalize_slug.return_value = "slug"
    mock_wiki.write_raw_source.side_effect = ValueError("bad content")
    
    res = i.add_raw_source("slug", "c")
    assert res["status"] == "error"
    assert "bad content" in res["error"]

def test_ingest_source_new(ti):
    i, tmp, common, mock_wiki, _ = ti
    mock_wiki.normalize_slug.return_value = "slug"
    mock_wiki.write_raw_source.return_value = tmp / "raw" / "slug.md"
    
    res = i.ingest_source("slug", "content", title="Title")
    assert res["status"] == "ok"
    assert res["summary_created"] is True
    mock_wiki.write_wiki_page.assert_called_once()

def test_ingest_source_exists(ti):
    i, tmp, common, mock_wiki, _ = ti
    mock_wiki.normalize_slug.return_value = "slug"
    mock_wiki.write_raw_source.return_value = tmp / "raw" / "slug.md"
    
    # Create summary already
    (tmp / "wiki" / "source-slug.md").write_text("exists")
    
    res = i.ingest_source("slug", "content")
    assert res["status"] == "ok"
    assert res["summary_created"] is False
    mock_wiki.write_wiki_page.assert_not_called()
    mock_wiki.render_index.assert_called_once()

def test_rebuild_index(ti):
    i, tmp, common, _, mock_index = ti
    mock_index.rebuild_index.return_value = {"page_count": 10}
    
    res = i.rebuild_index(with_obsidian=True)
    assert res["status"] == "ok"
    assert res["manifest"]["page_count"] == 10
    mock_index.rebuild_index.assert_called_once_with(tmp, with_obsidian=True)

def test_rebuild_index_error(ti):
    i, tmp, common, _, mock_index = ti
    mock_index.rebuild_index.side_effect = Exception("boom")
    
    res = i.rebuild_index()
    assert res["status"] == "error"
    assert "boom" in res["message"]

def test_index_status(ti):
    i, tmp, common, _, mock_index = ti
    mock_index.index_status.return_value = {"ok": True}
    res = i.index_status()
    assert res["ok"] is True

def test_search_brain(ti):
    i, tmp, common, _, mock_index = ti
    mock_index.search_brain.return_value = [{"slug": "p1"}]
    res = i.search_brain("query")
    assert res["count"] == 1
    assert res["results"][0]["slug"] == "p1"

def test_get_backlinks(ti):
    i, tmp, common, _, mock_index = ti
    mock_index.get_backlinks.return_value = ["p2"]
    res = i.get_backlinks("p1")
    assert res["count"] == 1
    assert "p2" in res["backlinks"]

def test_get_source_map(ti):
    i, tmp, common, _, mock_index = ti
    mock_index.get_source_map.return_value = {"p1": "r1"}
    res = i.get_source_map("p1")
    assert res["source_map"]["p1"] == "r1"

def test_vector_tools(ti):
    i, tmp, common, _, _ = ti
    mock_vector = MagicMock()
    
    # tools_index imports _run_brain_vector from tools_misc inside the function
    with patch("tools_misc._run_brain_vector", mock_vector, create=True):
        mock_index_res = {"status": "ok"}
        mock_vector.return_value = mock_index_res
        
        assert i.vector_status() == mock_index_res
        mock_vector.assert_called_with(["status"])
        
        assert i.vector_search("q", 3) == mock_index_res
        mock_vector.assert_called_with(["search", "q", "--top-k", "3"])
