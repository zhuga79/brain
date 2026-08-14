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
def tp(tmp_path, monkeypatch):
    """temp_brain: isolated BRAIN_PATH with minimal structure, reloaded modules."""
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))

    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "log.md").write_text("# Log\n\n")
    (tmp_path / "prd").mkdir()
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "active.md").write_text("# Active tasks\n")
    (tmp_path / "tasks" / "done.md").write_text("# Done tasks\n")

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
    for mod_name in ["common", "tools_prd"]:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    import common
    import tools_prd as p

    # Sync globals
    monkeypatch.setattr(common, "BRAIN", tmp_path)
    monkeypatch.setattr(p, "BRAIN", tmp_path, raising=False)
    monkeypatch.setattr(common, "ACTIVE", tmp_path / "tasks" / "active.md")
    monkeypatch.setattr(p, "ACTIVE", tmp_path / "tasks" / "active.md", raising=False)
    monkeypatch.setattr(common, "DONE", tmp_path / "tasks" / "done.md")
    monkeypatch.setattr(p, "DONE", tmp_path / "tasks" / "done.md", raising=False)
    monkeypatch.setattr(common, "PRD_DIR", tmp_path / "prd")
    monkeypatch.setattr(p, "PRD_DIR", tmp_path / "prd", raising=False)
    
    monkeypatch.setattr(common, "git_commit", lambda *a, **k: None)
    monkeypatch.setattr(p, "git_commit", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(common, "append_log", lambda *a, **k: None)
    monkeypatch.setattr(p, "append_log", lambda *a, **k: None, raising=False)

    yield p, tmp_path, common

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_init_prd_success(tp):
    p, tmp, common = tp
    (tmp / "prd" / "_TEMPLATE.md").write_text("ID: <task-id> Title: <Title> TS: <ts>")
    
    with patch("tools_prd.find_task_block", return_value="block"), \
         patch("tools_prd.parse_block", return_value={"title": "My Task"}):
        res = p.init_prd("t-1")
        assert res["status"] == "ok"
        content = (tmp / "prd" / "t-1.md").read_text()
        assert "ID: t-1" in content
        assert "Title: My Task" in content

def test_init_prd_exists(tp):
    p, tmp, common = tp
    (tmp / "prd" / "t-1.md").write_text("exists")
    res = p.init_prd("t-1")
    assert res["status"] == "error"
    assert "already exists" in res["error"]

def test_commit_prd_success(tp):
    p, tmp, common = tp
    prd_content = """---
id: t-1
status: draft
---
## Subtasks

- [ ] [P1] sub1 — Subtask 1
      role: developer
      depends_on: [sub2]

- [ ] [P2] sub2 — Subtask 2
      acceptance: ok
"""
    (tmp / "prd" / "t-1.md").write_text(prd_content)
    
    res = p.commit_prd("t-1")
    assert res["status"] == "ok"
    assert res["subtasks_count"] == 2
    
    active = (tmp / "tasks" / "active.md").read_text()
    assert "t-1-sub1" in active
    assert "depends_on: [t-1-sub2]" in active
    assert "parent: t-1" in active
    
    # Check PRD status updated
    assert "status: committed" in (tmp / "prd" / "t-1.md").read_text()

def test_commit_prd_already_committed(tp):
    p, tmp, common = tp
    (tmp / "prd" / "t-1.md").write_text("status: committed\n## Subtasks\n- [ ] [P1] sub1 — T")
    active = tmp / "tasks" / "active.md"
    active.write_text("# Active tasks\n\n## PRD subtasks of t-1\n\n- [ ] [P1] t-1-sub1 — T\n      parent: t-1\n")
    res = p.commit_prd("t-1")
    assert res["status"] == "ok"
    assert res["appended_count"] == 0
    assert active.read_text().count("t-1-sub1") == 1


def test_commit_prd_recovers_committed_prd_with_missing_queue(tp):
    p, tmp, common = tp
    (tmp / "prd" / "t-1.md").write_text(
        "status: committed\n## Subtasks\n\n- [ ] [P1] sub1 — T\n      acceptance: ok\n",
        encoding="utf-8",
    )
    res = p.commit_prd("t-1")
    assert res["status"] == "ok"
    assert res["recovered"] is True
    assert res["appended_count"] == 1
    active = (tmp / "tasks" / "active.md").read_text(encoding="utf-8")
    assert active.count("t-1-sub1") == 1


def test_commit_prd_rejects_duplicate_normalized_ids_without_writes(tp):
    p, tmp, common = tp
    prd = tmp / "prd" / "t-1.md"
    prd.write_text(
        """status: draft
## Subtasks

- [ ] [P1] sub1 — First
      acceptance: ok

- [ ] [P1] t-1-sub1 — Duplicate
      acceptance: ok
""",
        encoding="utf-8",
    )
    active = tmp / "tasks" / "active.md"
    active_before = active.read_bytes()
    prd_before = prd.read_bytes()

    res = p.commit_prd("t-1")
    assert res["status"] == "error"
    assert "duplicate normalized PRD subtask ids" in res["error"]
    assert active.read_bytes() == active_before
    assert prd.read_bytes() == prd_before

def test_get_prd_status(tp):
    p, tmp, common = tp
    (tmp / "prd" / "t-1.md").write_text("status: committed")
    (tmp / "tasks" / "active.md").write_text("""
- [ ] [P1] t-1-sub1 — T1
      parent: t-1
- [x] [P1] t-1-sub2 — T2
      parent: t-1
""")
    
    res = p.get_prd_status("t-1")
    assert res["prd_status"] == "committed"
    assert res["total"] == 2
    assert res["done"] == 1

def test_read_prd(tp):
    p, tmp, common = tp
    (tmp / "prd" / "t-1.md").write_text("CONTENT")
    res = p.read_prd("t-1")
    assert res["content"] == "CONTENT"
    
    assert p.read_prd("missing")["status"] == "error"
