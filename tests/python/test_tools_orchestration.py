"""Focused MCP queue integrity tests.

These cover the MCP mutation tools that must go through the unified
brain_app.queue / brain_core.taskfile path instead of ad hoc file rewrites.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path.cwd() / "runtime" / "lib"))
sys.path.insert(0, str(Path.cwd() / "runtime" / "mcp"))


ACTIVE_CONTENT = (
    "# Active\n\n"
    "## P1\n\n"
    "- [ ] [P1] t-test — Test task\n"
    "      role: developer   mode: solo\n"
)


def _make_fastmcp_mock():
    mock = MagicMock()
    mock.tool.return_value = lambda f: f
    return mock


@pytest.fixture
def tb(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))

    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "log.md").write_text("# Log\n\n", encoding="utf-8")
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "active.md").write_text(ACTIVE_CONTENT, encoding="utf-8")
    (tmp_path / "tasks" / "done.md").write_text("# Done\n\n", encoding="utf-8")
    (tmp_path / ".locks").mkdir()

    fake_mcp_pkg = types.ModuleType("mcp")
    fake_mcp_server = types.ModuleType("mcp.server")
    fake_mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")
    fake_mcp_fastmcp.FastMCP = lambda *a, **k: _make_fastmcp_mock()
    fake_mcp_pkg.server = fake_mcp_server
    fake_mcp_server.fastmcp = fake_mcp_fastmcp
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp_pkg)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_mcp_server)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_mcp_fastmcp)

    for mod_name in list(sys.modules.keys()):
        if mod_name in ("common", "tools_orchestration", "tools_tasks"):
            del sys.modules[mod_name]

    import common
    import tools_orchestration as orchestration
    import tools_tasks

    locks_path = tmp_path / ".locks"
    for mod in (common, orchestration, tools_tasks):
        monkeypatch.setattr(mod, "LOCKS", locks_path, raising=False)
        monkeypatch.setattr(mod, "ACTIVE", tmp_path / "tasks" / "active.md", raising=False)
        monkeypatch.setattr(mod, "DONE", tmp_path / "tasks" / "done.md", raising=False)
        monkeypatch.setattr(mod, "BRAIN", tmp_path, raising=False)

    monkeypatch.setattr(common, "git_commit", lambda *a, **k: None)
    monkeypatch.setattr(orchestration, "git_commit", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(tools_tasks, "git_commit", lambda *a, **k: None, raising=False)

    return orchestration, tools_tasks, tmp_path, common


def _snapshot(tmp_path: Path) -> tuple[str, str, str, str]:
    owner = tmp_path / ".locks" / "t-test" / "owner"
    return (
        (tmp_path / "tasks" / "active.md").read_text(encoding="utf-8"),
        (tmp_path / "tasks" / "done.md").read_text(encoding="utf-8"),
        (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8"),
        owner.read_text(encoding="utf-8") if owner.exists() else "",
    )


def test_take_task_rejects_empty_agent_before_lock_or_write(tb):
    t, _, tmp, _ = tb
    before = _snapshot(tmp)

    res = t.take_task("t-test", "")

    assert res["status"] == "error"
    assert "agent" in res["error"].lower()
    assert _snapshot(tmp) == before
    assert not (tmp / ".locks" / "t-test").exists()


def test_take_task_uses_queue_contract_and_creates_lock(tb):
    t, _, tmp, _ = tb

    res = t.take_task("t-test", "agent-1")

    assert res["status"] == "ok"
    active = (tmp / "tasks" / "active.md").read_text(encoding="utf-8")
    assert "- [~] [P1] t-test" in active
    assert "by: agent-1" in active
    owner = (tmp / ".locks" / "t-test" / "owner").read_text(encoding="utf-8")
    assert owner.startswith("agent-1|")


def test_release_task_rejects_empty_agent_before_mutation(tb):
    t, _, tmp, _ = tb
    t.take_task("t-test", "agent-1")
    before = _snapshot(tmp)

    res = t.release_task("t-test", "")

    assert res["status"] == "error"
    assert "agent" in res["error"].lower()
    assert _snapshot(tmp) == before


def test_release_task_wrong_owner_rejected_without_mutation(tb):
    t, _, tmp, _ = tb
    t.take_task("t-test", "agent-1")
    before = _snapshot(tmp)

    res = t.release_task("t-test", "intruder")

    assert res["status"] == "error"
    assert "not intruder" in res["error"] or "owned by" in res["error"]
    assert _snapshot(tmp) == before


def test_release_task_owner_succeeds_and_removes_lock(tb):
    t, _, tmp, _ = tb
    t.take_task("t-test", "agent-1")

    res = t.release_task("t-test", "agent-1")

    assert res["status"] == "ok"
    active = (tmp / "tasks" / "active.md").read_text(encoding="utf-8")
    assert "- [ ] [P1] t-test" in active
    assert "started:" not in active
    assert "by:" not in active
    assert not (tmp / ".locks" / "t-test").exists()


def test_complete_task_requires_real_model_before_mutation(tb):
    t, _, tmp, _ = tb
    t.take_task("t-test", "agent-1")
    before = _snapshot(tmp)

    res = t.complete_task("t-test", "agent-1", model="", summary="done")

    assert res["status"] == "error"
    assert "model" in res["error"].lower()
    assert _snapshot(tmp) == before


@pytest.mark.parametrize("model", ["unsigned", "  "])
def test_complete_task_rejects_non_real_model_values(tb, model):
    t, _, tmp, _ = tb
    t.take_task("t-test", "agent-1")
    before = _snapshot(tmp)

    res = t.complete_task("t-test", "agent-1", model=model, summary="done")

    assert res["status"] == "error"
    assert "model" in res["error"].lower()
    assert _snapshot(tmp) == before


def test_complete_task_wrong_owner_rejected_without_mutation(tb):
    t, _, tmp, _ = tb
    t.take_task("t-test", "agent-1")
    before = _snapshot(tmp)

    res = t.complete_task("t-test", "intruder", model="openai-gpt-5.4", summary="done")

    assert res["status"] == "error"
    assert "not intruder" in res["error"] or "owned by" in res["error"]
    assert _snapshot(tmp) == before


def test_complete_task_owner_records_model_and_releases_lock(tb):
    t, _, tmp, _ = tb
    t.take_task("t-test", "agent-1")

    res = t.complete_task("t-test", "agent-1", model="openai-gpt-5.4", summary="done")

    assert res["status"] == "ok"
    assert "t-test" not in (tmp / "tasks" / "active.md").read_text(encoding="utf-8")
    done = (tmp / "tasks" / "done.md").read_text(encoding="utf-8")
    assert "t-test" in done
    assert "model: openai-gpt-5.4" in done
    assert "by: agent-1" in done
    assert not (tmp / ".locks" / "t-test").exists()


def test_mcp_block_task_requires_agent_and_preserves_state_on_error(tb):
    t, tools_tasks, tmp, _ = tb
    t.take_task("t-test", "agent-1")
    before = _snapshot(tmp)

    res = tools_tasks.block_task("t-test", "need info")

    assert res["status"] == "error"
    assert "agent" in res["error"].lower()
    assert _snapshot(tmp) == before


def test_mcp_block_task_wrong_owner_rejected_without_mutation(tb):
    t, tools_tasks, tmp, _ = tb
    t.take_task("t-test", "agent-1")
    before = _snapshot(tmp)

    res = tools_tasks.block_task("t-test", "need info", agent_id="intruder")

    assert res["status"] == "error"
    assert "not intruder" in res["error"] or "owned by" in res["error"]
    assert _snapshot(tmp) == before


def test_mcp_block_task_owner_succeeds_via_queue_contract(tb):
    t, tools_tasks, tmp, _ = tb
    t.take_task("t-test", "agent-1")

    res = tools_tasks.block_task("t-test", "need info", agent_id="agent-1")

    assert res["status"] == "ok"
    active = (tmp / "tasks" / "active.md").read_text(encoding="utf-8")
    assert "- [!] [P1] t-test" in active
    assert "t-test" not in (tmp / "tasks" / "done.md").read_text(encoding="utf-8")


def test_mcp_take_wrong_owner_and_complete_do_not_lose_updates(tb):
    t, _, tmp, _ = tb
    t.take_task("t-test", "agent-1")
    before = _snapshot(tmp)

    second_take = t.take_task("t-test", "agent-2")
    intruder_complete = t.complete_task("t-test", "agent-2", model="openai-gpt-5.4")

    assert second_take.get("status") == "locked"
    assert intruder_complete["status"] == "error"
    assert _snapshot(tmp) == before
