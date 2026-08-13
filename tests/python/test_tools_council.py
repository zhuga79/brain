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
def tc(tmp_path, monkeypatch):
    """temp_brain: isolated BRAIN_PATH with minimal structure, reloaded modules."""
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))

    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "log.md").write_text("# Log\n\n")
    (tmp_path / "council").mkdir()
    (tmp_path / "teams").mkdir()

    # Fake MCP package structure
    fake_mcp_pkg = types.ModuleType("mcp")
    fake_mcp_server = types.ModuleType("mcp.server")
    fake_mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")
    fake_mcp_fastmcp.FastMCP = lambda *a, **k: _make_fastmcp_mock()
    fake_mcp_pkg.server = fake_mcp_server
    fake_mcp_server.fastmcp = fake_mcp_fastmcp
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp_pkg)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_mcp_server)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_mcp_fastmcp)

    # Force reload of common and tools_council to use the fake MCP and tmp BRAIN_PATH
    for mod_name in ["common", "tools_council"]:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    import common
    import tools_council as c

    # Sync module globals with tmp_path
    monkeypatch.setattr(common, "BRAIN", tmp_path)
    monkeypatch.setattr(c, "BRAIN", tmp_path, raising=False)
    
    # Stub disk-mutating/git operations
    monkeypatch.setattr(common, "git_commit", lambda *a, **k: None)
    monkeypatch.setattr(c, "git_commit", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(common, "append_log", lambda *a, **k: None)
    monkeypatch.setattr(c, "append_log", lambda *a, **k: None, raising=False)

    yield c, tmp_path, common

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_council_start_success(tc):
    c, tmp, common = tc
    task_id = "t-1"
    
    with patch("tools_council.find_task_block", return_value="some block"), \
         patch("tools_council.parse_block", return_value={"council": ["developer", "reviewer"]}), \
         patch("tools_council.expand_council", return_value=["developer", "reviewer"]):
        
        res = c.council_start(task_id)
        assert res["status"] == "ok"
        assert sorted(res["roles"]) == ["developer", "reviewer"]
        assert (tmp / "council" / task_id / "developer.md").exists()
        assert (tmp / "council" / task_id / "reviewer.md").exists()

def test_council_start_errors(tc):
    c, tmp, common = tc
    
    # Task not found
    with patch("tools_council.find_task_block", return_value=None):
        res = c.council_start("missing")
        assert res["status"] == "error"
        assert "not found" in res["error"]
        
    # No council field
    with patch("tools_council.find_task_block", return_value="block"), \
         patch("tools_council.parse_block", return_value={"council": None}):
        res = c.council_start("t-1")
        assert res["status"] == "error"
        assert "no council: field" in res["error"]

def test_council_status(tc):
    c, tmp, common = tc
    task_id = "t-status"
    cdir = tmp / "council" / task_id
    cdir.mkdir(parents=True)
    
    # Empty status
    res = c.council_status(task_id)
    assert res["opinions"] == []
    assert res["synthesis"] is False
    
    # With opinions
    (cdir / "developer.md").write_text("written: TODO")
    (cdir / "reviewer.md").write_text("written: 2026-05-13")
    (cdir / "synthesis.md").write_text("done")
    
    res2 = c.council_status(task_id)
    assert len(res2["opinions"]) == 2
    ops = {o["role"]: o["pending"] for o in res2["opinions"]}
    assert ops["developer"] is True
    assert ops["reviewer"] is False
    assert res2["synthesis"] is True

def test_council_status_no_dir(tc):
    c, tmp, common = tc
    res = c.council_status("no-dir")
    assert res["status"] == "error"

def test_add_council_opinion(tc):
    c, tmp, common = tc
    task_id = "t-1"
    cdir = tmp / "council" / task_id
    cdir.mkdir(parents=True)
    (cdir / "developer.md").write_text("written: TODO")
    
    res = c.add_council_opinion(
        task_id, "developer", "agent-1", "model-1",
        "My Position", "My Reasoning", "My Risks", "My Rec"
    )
    assert res["status"] == "ok"
    content = (cdir / "developer.md").read_text()
    assert "agent: agent-1" in content
    assert "model: model-1" in content
    assert "## Position\nMy Position" in content
    
    # Error: no skeleton
    res2 = c.add_council_opinion(task_id, "missing", "a", "m", "p", "r", "k", "c")
    assert res2["status"] == "error"

def test_get_council_opinions(tc):
    c, tmp, common = tc
    task_id = "t-1"
    cdir = tmp / "council" / task_id
    cdir.mkdir(parents=True)
    (cdir / "developer.md").write_text("content developer")
    (cdir / "reviewer.md").write_text("written: TODO")
    (cdir / "synthesis.md").write_text("synth")
    
    # All non-TODO
    res = c.get_council_opinions(task_id)
    assert "developer" in res["opinions"]
    assert "reviewer" not in res["opinions"]
    assert "synthesis" not in res["opinions"]
    assert res["opinions"]["developer"] == "content developer"
    
    # Specific role
    res2 = c.get_council_opinions(task_id, "developer")
    assert res2["opinions"]["developer"] == "content developer"
    
    # Role error
    res3 = c.get_council_opinions(task_id, "missing")
    assert res3["status"] == "error"

def test_get_council_opinions_no_dir(tc):
    c, tmp, common = tc
    res = c.get_council_opinions("no-dir")
    assert res["status"] == "error"

def test_synthesize_council(tc):
    c, tmp, common = tc
    task_id = "t-synth"
    cdir = tmp / "council" / task_id
    cdir.mkdir(parents=True)
    (cdir / "developer.md").write_text("...")
    
    res = c.synthesize_council(
        task_id, "arbiter-1",
        positions={"developer": "TLDR"},
        agreement="All agree",
        disagreement="None",
        decision="Go ahead",
        reasoning="Because",
        open_questions="None",
        follow_up_tasks=["t-next"]
    )
    assert res["status"] == "ok"
    assert (cdir / "synthesis.md").exists()
    content = (cdir / "synthesis.md").read_text()
    assert "arbiter: arbiter-1" in content
    assert "inputs: [developer.md]" in content
    assert "- developer: TLDR" in content
    assert "- t-next" in content

def test_synthesize_council_no_dir(tc):
    c, tmp, common = tc
    res = c.synthesize_council("no-dir", "a", {}, "a", "d", "d", "r")
    assert res["status"] == "error"
