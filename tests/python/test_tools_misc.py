import os
import sys
import types
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

def _make_fastmcp_mock():
    mock = MagicMock()
    mock.tool.return_value = lambda f: f
    return mock

@pytest.fixture
def tm(tmp_path, monkeypatch):
    """temp_brain: isolated BRAIN_PATH with minimal structure, reloaded modules."""
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))

    (tmp_path / "wiki").mkdir()
    (tmp_path / "tasks").mkdir()
    (tmp_path / "council").mkdir()
    (tmp_path / "doctrine").mkdir()
    (tmp_path / ".locks").mkdir()
    (tmp_path / ".brain" / "index").mkdir(parents=True)
    
    (tmp_path / "tasks" / "active.md").write_text("# Active\n")
    (tmp_path / "tasks" / "done.md").write_text("# Done\n")

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
    for mod_name in ["common", "tools_misc"]:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    import common
    import tools_misc as m

    # Sync globals
    monkeypatch.setattr(common, "BRAIN", tmp_path)
    monkeypatch.setattr(m, "BRAIN", tmp_path, raising=False)
    monkeypatch.setattr(common, "ACTIVE", tmp_path / "tasks" / "active.md")
    monkeypatch.setattr(m, "ACTIVE", tmp_path / "tasks" / "active.md", raising=False)
    monkeypatch.setattr(common, "LOCKS", tmp_path / ".locks")
    monkeypatch.setattr(m, "LOCKS", tmp_path / ".locks", raising=False)

    yield m, tmp_path, common

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_run_brain_vector(tm):
    m, tmp, common = tm
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
        res = m._run_brain_vector(["status"])
        assert res["ok"] is True
        assert res["output"] == "output"
        mock_run.assert_called_once()

def test_collect_dashboard_status(tm):
    m, tmp, common = tm
    # Tasks
    (tmp / "tasks" / "active.md").write_text("- [ ] [P1] t1 — T1\n- [~] [P1] t2 — T2")
    # Locks
    lock_dir = tmp / ".locks" / "t-lock"
    lock_dir.mkdir()
    (lock_dir / "owner").write_text("agent|1000|10")
    # Council
    (tmp / "council" / "t-council").mkdir()
    (tmp / "council" / "t-council" / "dev.md").write_text("...")
    # Index
    pages_json = tmp / ".brain" / "index" / "pages.json"
    pages_json.write_text(json.dumps([{"slug": "p1"}, {"slug": "p2"}]))
    
    res = m._collect_dashboard_status()
    assert res["tasks"]["summary"]["open"] == 1
    assert res["tasks"]["summary"]["in_progress"] == 1
    assert res["locks"]["count"] == 1
    assert res["council"]["count"] == 1
    assert res["index"]["page_count"] == 2

def test_dashboard_status(tm):
    m, tmp, common = tm
    with patch("tools_misc._collect_dashboard_status", return_value={"ok": True}):
        assert m.dashboard_status() == {"ok": True}

def test_dashboard_export(tm):
    m, tmp, common = tm
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Exported to /tmp/dash.html", stderr="")
        res = m.dashboard_export("/tmp/dash.html")
        assert res["ok"] is True
        assert "/tmp/dash.html" in res["path"]

def test_doctrines(tm):
    m, tmp, common = tm
    (tmp / "doctrine" / "d1.md").write_text("Rule: test rule")
    
    # List
    res_list = m.list_doctrines()
    assert res_list["count"] == 1
    assert res_list["doctrines"][0]["slug"] == "d1"
    
    # Search
    res_search = m.search_doctrines("rule")
    assert res_search["count"] == 1
    assert "test rule" in res_search["results"][0]["matches"][0]
    
    assert m.search_doctrines("missing")["count"] == 0
