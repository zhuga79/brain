"""Focused MCP queue integrity tests.

These cover the MCP mutation tools that must go through the unified
brain_app.queue / brain_core.taskfile path instead of ad hoc file rewrites.
"""

from __future__ import annotations

import os
import threading
import sys
import types
import time
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


def _active_and_done(tmp_path: Path) -> tuple[str, str]:
    return (
        (tmp_path / "tasks" / "active.md").read_text(encoding="utf-8"),
        (tmp_path / "tasks" / "done.md").read_text(encoding="utf-8"),
    )


def _write_tasks(tmp_path: Path, *blocks: str) -> None:
    body = "\n\n".join(blocks)
    (tmp_path / "tasks" / "active.md").write_text(f"# Active\n\n## P1\n\n{body}\n", encoding="utf-8")


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


def test_take_nonexistent_task_releases_lock(tb):
    t, _, tmp, _ = tb

    res = t.take_task("t-no-such", "agent-1")

    assert res["status"] == "error"
    assert not (tmp / ".locks" / "t-no-such").exists()


def test_take_adds_started_metadata(tb):
    t, _, tmp, _ = tb

    t.take_task("t-test", "agent-meta")

    active = (tmp / "tasks" / "active.md").read_text(encoding="utf-8")
    assert "started:" in active
    assert "by: agent-meta" in active


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


@pytest.mark.parametrize(
    "model",
    ["placeholder-summary-text", "cleanup", "summary", "openai-gpt", "claude-opus"],
)
def test_complete_task_rejects_placeholders_and_unversioned_models(tb, model):
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


def test_complete_task_accepts_external_versioned_models(tb):
    t, _, tmp, _ = tb
    t.take_task("t-test", "agent-1")

    res = t.complete_task("t-test", "agent-1", model="grok-4.6", summary="done")

    assert res["status"] == "ok"
    done = (tmp / "tasks" / "done.md").read_text(encoding="utf-8")
    assert "model: grok-4.6" in done


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


def test_lock_status_reports_free_and_all_locks(tb):
    t, _, _, _ = tb

    assert t.lock_status("t-free")["status"] == "free"
    assert t.lock_status()["locks"] == []

    t.acquire_lock("t-test", "agent-1", ttl=300)
    single = t.lock_status("t-test")
    assert single["status"] == "locked"
    assert single["owner"] == "agent-1"
    assert single["ttl"] == 300

    listed = t.lock_status()["locks"]
    assert len(listed) == 1
    assert listed[0]["task_id"] == "t-test"


def test_cleanup_locks_removes_stale_and_corrupt_entries_but_skips_symlink(tb):
    t, _, tmp, _ = tb
    stale = tmp / ".locks" / "t-stale"
    stale.mkdir()
    (stale / "owner").write_text("agent|1|1\n", encoding="utf-8")

    corrupt = tmp / ".locks" / "t-corrupt"
    corrupt.mkdir()
    (corrupt / "owner").write_text("garbage", encoding="utf-8")

    missing = tmp / ".locks" / "t-noowner"
    missing.mkdir()

    external = tmp / "external"
    external.mkdir()
    (external / "important.txt").write_text("keep", encoding="utf-8")
    os.symlink(external, tmp / ".locks" / "t-sym")

    res = t.cleanup_locks()

    assert res["cleaned"] >= 3
    assert not stale.exists()
    assert not corrupt.exists()
    assert not missing.exists()
    assert (tmp / ".locks" / "t-sym").exists()
    assert (external / "important.txt").exists()


def test_release_lock_reports_no_lock_and_rejects_foreign_owner(tb):
    t, _, _, _ = tb

    assert t.release_lock("t-missing")["status"] == "no_lock"
    t.acquire_lock("t-test", "agent-1")
    res = t.release_lock("t-test", "agent-2")
    assert res["status"] == "error"
    assert "agent-1" in res["error"]


@pytest.mark.parametrize("agent_id", ["", "   ", "agent 2", "../escape"])
def test_release_lock_rejects_invalid_actor_before_mutation(tb, agent_id):
    t, _, tmp, _ = tb
    t.acquire_lock("t-test", "agent-1")
    before = _snapshot(tmp)

    res = t.release_lock("t-test", agent_id)

    assert res["status"] == "error"
    assert "agent_id" in res["error"]
    assert _snapshot(tmp) == before


def test_release_lock_force_requires_reason_and_valid_actor(tb):
    t, _, tmp, _ = tb
    t.acquire_lock("t-test", "agent-1")
    before = _snapshot(tmp)

    missing_reason = t.release_lock("t-test", "agent-2", force=True)
    bad_actor = t.release_lock("t-test", "agent 2", force=True, reason="cleanup")

    assert missing_reason["status"] == "error"
    assert "reason" in missing_reason["error"]
    assert bad_actor["status"] == "error"
    assert "agent_id" in bad_actor["error"]
    assert _snapshot(tmp) == before


def test_release_lock_force_can_remove_foreign_or_corrupt_lock_with_audit(tb):
    t, _, tmp, _ = tb
    t.acquire_lock("t-foreign", "agent-1")

    foreign = t.release_lock(
        "t-foreign",
        "agent-2",
        force=True,
        reason="operator stale lock cleanup",
    )

    assert foreign["status"] == "ok"
    assert not (tmp / ".locks" / "t-foreign").exists()
    log = (tmp / "wiki" / "log.md").read_text(encoding="utf-8")
    assert "force" in log
    assert "operator stale lock cleanup" in log

    corrupt = tmp / ".locks" / "t-corrupt"
    corrupt.mkdir()
    (corrupt / "owner").write_text("|1|60\n", encoding="utf-8")

    force_corrupt = t.release_lock(
        "t-corrupt",
        "agent-2",
        force=True,
        reason="clear corrupt owner",
    )

    assert force_corrupt["status"] == "ok"
    assert not corrupt.exists()


def test_release_lock_rejects_invalid_task_id_before_mutation(tb):
    t, _, tmp, _ = tb
    t.acquire_lock("t-test", "agent-1")
    before = _snapshot(tmp)

    res = t.release_lock("../escape", "agent-1")

    assert res["status"] == "error"
    assert "invalid task id" in res["error"]
    assert _snapshot(tmp) == before


def test_release_lock_symlink_force_refused_without_touching_target(tb):
    t, _, tmp, _ = tb
    external = tmp / "external"
    external.mkdir()
    important = external / "important.txt"
    important.write_text("keep", encoding="utf-8")
    os.symlink(external, tmp / ".locks" / "t-sym")

    res = t.release_lock(
        "t-sym",
        "agent-2",
        force=True,
        reason="security cleanup",
    )

    assert res["status"] == "error"
    assert "symlink" in res["error"]
    assert important.exists()
    assert (tmp / ".locks" / "t-sym").is_symlink()


def test_refresh_lock_requires_owner(tb):
    t, _, _, _ = tb

    assert t.refresh_lock("t-test", "agent-1")["status"] == "error"
    t.acquire_lock("t-test", "agent-1", ttl=10)
    assert t.refresh_lock("t-test", "agent-1", ttl=20)["status"] == "ok"
    assert t.refresh_lock("t-test", "agent-2", ttl=20)["status"] == "error"


def test_get_task_bundle_reports_task_lock_council_and_index(tb):
    t, _, tmp, _ = tb
    council_dir = tmp / "council" / "t-test"
    council_dir.mkdir(parents=True)
    (council_dir / "architect.md").write_text("# opinion", encoding="utf-8")

    bundle = t.get_task_bundle("t-test")
    assert bundle["task"]["id"] == "t-test"
    assert bundle["task"]["state"] != "not_found"
    assert bundle["lock"]["held"] is False
    assert bundle["council"]["exists"] is True
    assert "architect.md" in bundle["council"]["files"]
    assert "health" in bundle["index"]

    t.take_task("t-test", "agent-1")
    locked_bundle = t.get_task_bundle("t-test")
    assert locked_bundle["lock"]["held"] is True
    assert locked_bundle["lock"]["owner"] == "agent-1"


def test_get_task_bundle_reports_missing_task(tb):
    t, _, _, _ = tb
    bundle = t.get_task_bundle("t-no-such")
    assert bundle["task"]["state"] == "not_found"
    assert bundle["task"]["id"] == "t-no-such"


def test_take_task_concurrency_same_task_has_one_winner_no_corruption(tb):
    t, _, tmp, _ = tb
    barrier = threading.Barrier(2)
    results: list[dict] = []

    def worker(agent_id: str) -> None:
        barrier.wait()
        results.append(t.take_task("t-test", agent_id))

    threads = [
        threading.Thread(target=worker, args=("agent-1",)),
        threading.Thread(target=worker, args=("agent-2",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    ok_results = [res for res in results if res.get("status") == "ok"]
    locked_results = [res for res in results if res.get("status") == "locked"]
    assert len(ok_results) == 1
    assert len(locked_results) == 1
    active = (tmp / "tasks" / "active.md").read_text(encoding="utf-8")
    assert active.count("- [~] [P1] t-test") == 1
    assert active.count("started:") == 1
    assert active.count("by: ") == 1
    owner = (tmp / ".locks" / "t-test" / "owner").read_text(encoding="utf-8")
    assert owner.split("|", 1)[0] == ok_results[0]["owner"]


def test_complete_task_concurrency_different_tasks_persists_both_mutations(tb):
    t, _, tmp, _ = tb
    _write_tasks(
        tmp,
        "- [~] [P1] t-one — One\n      role: developer   mode: solo\n      started: 2026-08-14T10:00:00Z\n      by: agent-1",
        "- [~] [P1] t-two — Two\n      role: developer   mode: solo\n      started: 2026-08-14T10:00:00Z\n      by: agent-2",
    )
    t.acquire_lock("t-one", "agent-1")
    t.acquire_lock("t-two", "agent-2")
    barrier = threading.Barrier(2)
    results: list[dict] = []

    def worker(task_id: str, agent_id: str, model: str) -> None:
        barrier.wait()
        results.append(t.complete_task(task_id, agent_id, model=model, summary=f"done {task_id}"))

    threads = [
        threading.Thread(target=worker, args=("t-one", "agent-1", "openai-gpt-5.4")),
        threading.Thread(target=worker, args=("t-two", "agent-2", "claude-opus-4-8")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [res["status"] for res in results].count("ok") == 2
    active, done = _active_and_done(tmp)
    assert "t-one" not in active
    assert "t-two" not in active
    assert "model: openai-gpt-5.4" in done
    assert "model: claude-opus-4-8" in done
    assert "by: agent-1" in done
    assert "by: agent-2" in done
    assert not (tmp / ".locks" / "t-one").exists()
    assert not (tmp / ".locks" / "t-two").exists()
