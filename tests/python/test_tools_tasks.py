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
def tt(tmp_path, monkeypatch):
    """temp_brain: isolated BRAIN_PATH with minimal structure, reloaded modules."""
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))

    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "log.md").write_text("# Log\n\n")
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "active.md").write_text("# Active tasks\n")

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
    for mod_name in ["common", "tools_tasks"]:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    import common
    import tools_tasks as t

    # Sync globals
    monkeypatch.setattr(common, "BRAIN", tmp_path)
    monkeypatch.setattr(t, "BRAIN", tmp_path, raising=False)
    monkeypatch.setattr(common, "ACTIVE", tmp_path / "tasks" / "active.md")
    monkeypatch.setattr(t, "ACTIVE", tmp_path / "tasks" / "active.md", raising=False)
    
    monkeypatch.setattr(common, "git_commit", lambda *a, **k: None)
    monkeypatch.setattr(t, "git_commit", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(common, "append_log", lambda *a, **k: None)
    monkeypatch.setattr(t, "append_log", lambda *a, **k: None, raising=False)

    yield t, tmp_path, common

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_list_tasks(tt):
    t, tmp, common = tt
    (tmp / "tasks" / "active.md").write_text("""
- [ ] [P1] t1 — T1
      role: developer
- [~] [P1] t2 — T2
- [!] [P1] t3 — T3
""")
    
    # Default (open)
    res = t.list_tasks()
    assert len(res["tasks"]) == 1
    assert res["tasks"][0]["id"] == "t1"
    
    # Filter status
    res2 = t.list_tasks(status="in_progress")
    assert len(res2["tasks"]) == 1
    assert res2["tasks"][0]["id"] == "t2"
    
    # All
    res3 = t.list_tasks(status="all")
    assert len(res3["tasks"]) == 3

def test_get_task(tt):
    t, tmp, common = tt
    (tmp / "tasks" / "active.md").write_text("- [ ] [P1] t1 — Title\n      role: dev\n")

    res = t.get_task("t1")
    assert res["task"]["id"] == "t1"
    assert "Title" in res["raw"]


def test_get_task_missing(tt):
    t, tmp, common = tt
    assert "error" in t.get_task("t-nope")


def test_get_next_task(tt):
    t, tmp, common = tt
    (tmp / "tasks" / "done.md").write_text("# Done\n")
    (tmp / "tasks" / "active.md").write_text("""
- [ ] [P1] t1 — T1
      depends_on: [t2]
- [ ] [P1] t2 — T2
""")
    # t1 ждёт t2, значит доступна t2
    assert t.get_next_task()["task"]["id"] == "t2"

    (tmp / "tasks" / "active.md").write_text("- [ ] [P1] t2 — T2\n      depends_on: [t-missing]\n")
    res = t.get_next_task()
    assert res["task"] is None
    assert res["blocked"][0]["id"] == "t2"


def test_add_task(tt):
    t, tmp, common = tt
    res = t.add_task("New Task", role="dev", priority="P1")
    assert res["status"] == "added"

    content = (tmp / "tasks" / "active.md").read_text()
    assert res["id"] in content
    assert "role: dev" in content


def test_add_task_id_is_unique(tt):
    """Второй вызов с тем же заголовком не должен выдать занятый id."""
    t, tmp, common = tt
    first = t.add_task("Same title")["id"]
    second = t.add_task("Same title")["id"]
    assert first != second


def test_block_task(tt):
    t, tmp, common = tt
    (tmp / "tasks" / "active.md").write_text("- [ ] [P1] t1 — T1\n")

    res = t.block_task("t1", "need info", agent_id="agent-1")
    assert res["status"] == "ok"
    assert "- [!] [P1] t1 — T1" in (tmp / "tasks" / "active.md").read_text()


def test_block_task_missing(tt):
    t, tmp, common = tt
    (tmp / "tasks" / "active.md").write_text("# Active tasks\n")
    assert "error" in t.block_task("t-nope", "reason", agent_id="agent-1")


def test_get_task_deps(tt):
    t, tmp, common = tt
    (tmp / "tasks" / "active.md").write_text("- [ ] [P1] t1 — T1\n      depends_on: [t2]\n")
    (tmp / "tasks" / "done.md").write_text("- [x] [P1] t2 — T2\n")

    tree = t.get_task_deps("t1")["tree"]
    assert tree["id"] == "t1"
    assert tree["deps"][0]["id"] == "t2"
    assert tree["deps"][0]["state"] == "x"
