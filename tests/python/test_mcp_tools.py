import os
import pytest
import sys
import shutil
import importlib
from pathlib import Path
from unittest.mock import patch, MagicMock

# Create mock mcp before importing tools
from types import ModuleType

mcp_mock = ModuleType('mcp')
mcp_mock.server = ModuleType('mcp.server')
mcp_mock.server.fastmcp = ModuleType('mcp.server.fastmcp')

class FastMCP:
    def __init__(self, name):
        self.name = name
    def tool(self):
        return lambda f: f
    def resource(self, *args, **kwargs):
        return lambda f: f

mcp_mock.server.fastmcp.FastMCP = FastMCP
sys.modules['mcp'] = mcp_mock
sys.modules['mcp.server'] = mcp_mock.server
sys.modules['mcp.server.fastmcp'] = mcp_mock.server.fastmcp
sys.modules['fastmcp'] = mcp_mock.server.fastmcp

# Add runtime paths
sys.path.insert(0, str(Path.cwd() / "runtime" / "lib"))
sys.path.insert(0, str(Path.cwd() / "runtime" / "mcp"))

@pytest.fixture
def mock_brain(tmp_path, monkeypatch):
    brain = tmp_path / "brain"
    brain.mkdir()
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    
    (brain / "tasks").mkdir()
    (brain / "wiki").mkdir()
    (brain / "roles").mkdir()
    (brain / "doctrine").mkdir()
    (brain / "teams").mkdir()
    (brain / "prd").mkdir()
    (brain / ".locks").mkdir()
    (brain / "assets").mkdir()
    
    import common
    importlib.reload(common)
    import tools_tasks
    importlib.reload(tools_tasks)
    import tools_wiki
    importlib.reload(tools_wiki)
    
    return brain, common, tools_tasks, tools_wiki

def test_list_tasks(mock_brain):
    brain, common, tools_tasks, tools_wiki = mock_brain
    common.ACTIVE.write_text("- [ ] [P1] t1 — T1\n      role: dev   mode: solo\n- [ ] [P1] invalid\n")
    assert len(tools_tasks.list_tasks(role="dev", mode="solo", status="open")["tasks"]) == 1
    assert len(tools_tasks.list_tasks(role="pm")["tasks"]) == 0
    assert len(tools_tasks.list_tasks(mode="council")["tasks"]) == 0
    assert len(tools_tasks.list_tasks(status="done")["tasks"]) == 0
    
    common.ACTIVE.unlink()
    assert tools_tasks.list_tasks()["tasks"] == []

def test_get_task(mock_brain):
    brain, common, tools_tasks, tools_wiki = mock_brain
    common.ACTIVE.write_text("- [ ] [P1] t1 — Test\n")
    res = tools_tasks.get_task("t1")
    assert res["task"]["id"] == "t1"
    assert "error" in tools_tasks.get_task("missing")

def test_get_next_task(mock_brain):
    brain, common, tools_tasks, tools_wiki = mock_brain
    common.ACTIVE.write_text("- [ ] [P1] t1 — T1\n      depends_on: [t2]\n- [ ] [P1] t2 — T2\n")
    assert tools_tasks.get_next_task()["task"]["id"] == "t2"
    assert tools_tasks.get_next_task(role="developer")["task"]["id"] == "t2"
    assert tools_tasks.get_next_task(role="pm")["task"] is None
    
    common.ACTIVE.write_text("- [ ] [P1] t1 — T1\n      depends_on: [t2]\n")
    res = tools_tasks.get_next_task()
    assert res["task"] is None
    assert len(res["blocked"]) == 1
    
    common.ACTIVE.write_text("- [~] [P1] t1 — T1\n")
    assert tools_tasks.get_next_task()["task"] is None
    
    common.ACTIVE.unlink()
    assert tools_tasks.get_next_task()["task"] is None

def test_get_task_deps(mock_brain):
    brain, common, tools_tasks, tools_wiki = mock_brain
    common.ACTIVE.write_text("- [ ] [P1] t1 — T1\n      depends_on: [t1, missing]\n")
    res = tools_tasks.get_task_deps("t1")
    assert res["tree"]["deps"][0]["shown_above"] is True
    assert res["tree"]["deps"][1]["missing"] is True

def test_add_task(mock_brain):
    brain, common, tools_tasks, tools_wiki = mock_brain
    res = tools_tasks.add_task("new", council=["legal"], depends_on=["t1"])
    assert "new" in res["id"]

def test_block_task(mock_brain):
    brain, common, tools_tasks, tools_wiki = mock_brain
    common.ACTIVE.write_text("- [ ] [P1] t1 — Test\n")
    assert tools_tasks.block_task("t1", "x")["status"] == "ok"
    assert "error" in tools_tasks.block_task("missing", "x")

def test_wiki_tools(mock_brain):
    brain, common, tools_tasks, tools_wiki = mock_brain
    (brain / "MEMORY.md").write_text("mem")
    assert tools_wiki.get_memory()["content"] == "mem"
    (brain / "MEMORY.md").unlink()
    assert tools_wiki.get_memory()["content"] == ""
    
    (brain / "roles" / "dev.md").write_text("dev")
    assert tools_wiki.get_role("dev")["content"] == "dev"
    assert "error" in tools_wiki.get_role("missing")
    
    (brain / "teams" / "t1.md").write_text("roles: [r1]")
    assert "t1" in tools_wiki.list_teams()["teams"]
    
    (brain / "doctrine" / "d1.md").write_text("doc")
    assert tools_wiki.get_doctrine("d1")["content"] == "doc"
    assert len(tools_wiki.get_doctrine()["doctrines"]) == 1
    assert "error" in tools_wiki.get_doctrine("missing")
    
    for i in range(11):
        (brain / "wiki" / f"p{i}.md").write_text("test")
    assert len(tools_wiki.search_wiki("test")["results"]) == 10
    
    assert "p0" in tools_wiki.read_wiki_page("p0")["path"]
    assert "error" in tools_wiki.read_wiki_page("missing")

def test_wiki_write(mock_brain):
    brain, common, tools_tasks, tools_wiki = mock_brain
    assert tools_wiki.write_wiki_page("new-p", "content")["status"] == "ok"
    with patch("brain_wiki.write_wiki_page", side_effect=ValueError("fail")):
        assert "error" in tools_wiki.write_wiki_page("fail", "x")

def test_wiki_maintenance(mock_brain):
    brain, common, tools_tasks, tools_wiki = mock_brain
    assert tools_wiki.validate_wiki() is not None
    assert tools_wiki.lint_wiki(fix_index=True) is not None
    assert tools_wiki.regenerate_wiki_index() is not None
    assert tools_wiki.append_wiki_log("op")["status"] == "ok"

def test_coverage_shutil(mock_brain):
    brain, common, tools_tasks, tools_wiki = mock_brain
    shutil.rmtree(brain / "roles")
    assert tools_wiki.list_roles()["roles"] == []
    shutil.rmtree(brain / "teams")
    assert tools_wiki.list_teams()["teams"] == {}
    shutil.rmtree(brain / "doctrine")
    assert tools_wiki.get_doctrine()["doctrines"] == []
    shutil.rmtree(brain / "wiki")
    assert tools_wiki.search_wiki("q")["results"] == []
