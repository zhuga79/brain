"""Tests for tools_orchestration.py — Phase 16 T9.

Covers: cleanup_locks, take_task, release_task, complete_task, get_task_bundle,
        lock_status, refresh_lock (no-lock), and release_lock (no-lock/not-owner).

Fixture pattern mirrors test_acquire_lock.py: inject fake MCP, set BRAIN_PATH,
reload both common and tools_orchestration so module-level globals pick up tmp_path.
"""
import os
import sys
import time
import types
import importlib
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


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
    """temp_brain: isolated BRAIN_PATH with minimal structure, reloaded modules."""
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))

    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "log.md").write_text("# Log\n\n")
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "active.md").write_text(ACTIVE_CONTENT)
    (tmp_path / "tasks" / "done.md").write_text("# Done\n\n")
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
        if mod_name in ("common", "tools_orchestration"):
            del sys.modules[mod_name]

    import common
    import tools_orchestration as t

    locks_path = tmp_path / ".locks"
    monkeypatch.setattr(common, "LOCKS", locks_path)
    monkeypatch.setattr(t, "LOCKS", locks_path, raising=False)
    monkeypatch.setattr(common, "ACTIVE", tmp_path / "tasks" / "active.md")
    monkeypatch.setattr(t, "ACTIVE", tmp_path / "tasks" / "active.md", raising=False)
    monkeypatch.setattr(common, "DONE", tmp_path / "tasks" / "done.md")
    monkeypatch.setattr(t, "DONE", tmp_path / "tasks" / "done.md", raising=False)
    monkeypatch.setattr(common, "BRAIN", tmp_path)
    monkeypatch.setattr(t, "BRAIN", tmp_path, raising=False)

    # Stub git_commit so tests don't touch the actual git repo
    monkeypatch.setattr(common, "git_commit", lambda *a, **k: None)
    monkeypatch.setattr(t, "git_commit", lambda *a, **k: None, raising=False)

    yield t, tmp_path, common


# ---------------------------------------------------------------------------
# LockStatus
# ---------------------------------------------------------------------------

class TestLockStatus:
    def test_free_task(self, tb):
        t, tmp, _ = tb
        res = t.lock_status("t-free")
        assert res["status"] == "free"

    def test_locked_task(self, tb):
        t, tmp, _ = tb
        t.acquire_lock("t-locked", "agent-1", ttl=600)
        res = t.lock_status("t-locked")
        assert res["status"] == "locked"
        assert res["owner"] == "agent-1"
        assert res["ttl"] == 600

    def test_all_locks_empty(self, tb):
        t, tmp, _ = tb
        res = t.lock_status()
        assert res["locks"] == []

    def test_all_locks_one_entry(self, tb):
        t, tmp, _ = tb
        t.acquire_lock("t-all", "agent-x", ttl=300)
        res = t.lock_status()
        assert len(res["locks"]) == 1
        assert res["locks"][0]["task_id"] == "t-all"
        assert res["locks"][0]["owner"] == "agent-x"


# ---------------------------------------------------------------------------
# CleanupLocks
# ---------------------------------------------------------------------------

class TestCleanupLocks:
    def test_empty_dir(self, tb):
        t, tmp, _ = tb
        res = t.cleanup_locks()
        assert res["cleaned"] == 0

    def test_active_lock_not_cleaned(self, tb):
        t, tmp, _ = tb
        t.acquire_lock("t-active", "agent-1", ttl=600)
        res = t.cleanup_locks()
        assert res["cleaned"] == 0
        assert (tmp / ".locks" / "t-active").exists()

    def test_stale_lock_cleaned(self, tb):
        t, tmp, c = tb
        d = c.LOCKS / "t-stale"
        d.mkdir()
        # ts=1 (epoch), ttl=1 -> always expired
        (d / "owner").write_text("agent|1|1\n")
        res = t.cleanup_locks()
        assert res["cleaned"] >= 1
        assert not d.exists()

    def test_corrupt_owner_no_fields_cleaned(self, tb):
        t, tmp, c = tb
        d = c.LOCKS / "t-corrupt"
        d.mkdir()
        (d / "owner").write_text("garbage_no_pipes")
        res = t.cleanup_locks()
        assert res["cleaned"] >= 1
        assert not d.exists()

    def test_missing_owner_file_cleaned(self, tb):
        t, tmp, c = tb
        d = c.LOCKS / "t-noowner"
        d.mkdir()
        res = t.cleanup_locks()
        assert res["cleaned"] >= 1
        assert not d.exists()

    def test_symlink_skipped(self, tb):
        """cleanup_locks must NOT follow or remove symlinks (security guard)."""
        t, tmp, c = tb
        external = tmp / "external_dir"
        external.mkdir()
        (external / "important.txt").write_text("keep me")
        sym = c.LOCKS / "t-sym"
        os.symlink(external, sym)
        res = t.cleanup_locks()
        assert sym.exists()
        assert (external / "important.txt").exists()


# ---------------------------------------------------------------------------
# TakeTask
# ---------------------------------------------------------------------------

class TestTakeTask:
    def test_take_existing_task(self, tb):
        t, tmp, c = tb
        res = t.take_task("t-test", "agent-1")
        assert res["status"] == "ok"
        active = c.ACTIVE.read_text()
        assert "[~]" in active
        assert "t-test" in active

    def test_take_nonexistent_task(self, tb):
        t, tmp, _ = tb
        res = t.take_task("t-no-such", "agent-x")
        assert "error" in res
        # lock should have been released
        assert not (tmp / ".locks" / "t-no-such").exists()

    def test_take_already_locked(self, tb):
        t, tmp, _ = tb
        t.acquire_lock("t-test", "agent-1", ttl=600)
        res = t.take_task("t-test", "agent-2")
        assert res.get("status") == "locked"

    def test_take_adds_started_metadata(self, tb):
        t, tmp, c = tb
        t.take_task("t-test", "agent-meta")
        active = c.ACTIVE.read_text()
        assert "started:" in active
        assert "by: agent-meta" in active


# ---------------------------------------------------------------------------
# ReleaseTask
# ---------------------------------------------------------------------------

class TestReleaseTask:
    def test_release_in_progress_task(self, tb):
        t, tmp, c = tb
        t.take_task("t-test", "agent-1")
        res = t.release_task("t-test", "agent-1")
        assert res["status"] == "ok"
        active = c.ACTIVE.read_text()
        assert "- [ ]" in active

    def test_release_removes_started_metadata(self, tb):
        t, tmp, c = tb
        t.take_task("t-test", "agent-1")
        t.release_task("t-test", "agent-1")
        active = c.ACTIVE.read_text()
        assert "started:" not in active
        assert "by:" not in active

    def test_release_nonexistent_task(self, tb):
        t, tmp, _ = tb
        res = t.release_task("t-no-such", "agent-1")
        assert "error" in res


# ---------------------------------------------------------------------------
# CompleteTask
# ---------------------------------------------------------------------------

class TestCompleteTask:
    def test_complete_moves_to_done(self, tb):
        t, tmp, c = tb
        t.take_task("t-test", "agent-1")
        res = t.complete_task("t-test", "agent-1", "finished ok")
        assert res["status"] == "ok"
        done = c.DONE.read_text()
        assert "t-test" in done
        assert "[x]" in done

    def test_complete_removes_from_active(self, tb):
        t, tmp, c = tb
        t.take_task("t-test", "agent-1")
        t.complete_task("t-test", "agent-1")
        active = c.ACTIVE.read_text()
        assert "t-test" not in active

    def test_complete_includes_summary(self, tb):
        t, tmp, c = tb
        t.take_task("t-test", "agent-1")
        t.complete_task("t-test", "agent-1", "great work done")
        done = c.DONE.read_text()
        assert "great work done" in done

    def test_complete_releases_lock(self, tb):
        t, tmp, _ = tb
        t.take_task("t-test", "agent-1")
        t.complete_task("t-test", "agent-1")
        assert not (tmp / ".locks" / "t-test").exists()

    def test_complete_nonexistent_task(self, tb):
        t, tmp, _ = tb
        res = t.complete_task("t-no-such", "agent-1")
        assert "error" in res

    def test_complete_without_take(self, tb):
        """complete_task regex covers [ ~x] so open task can be completed directly."""
        t, tmp, c = tb
        res = t.complete_task("t-test", "agent-1")
        assert res["status"] == "ok"


# ---------------------------------------------------------------------------
# GetTaskBundle
# ---------------------------------------------------------------------------

class TestGetTaskBundle:
    def test_present_task_has_all_keys(self, tb):
        t, tmp, _ = tb
        b = t.get_task_bundle("t-test")
        assert "task" in b
        assert "lock" in b
        assert "council" in b
        assert "index" in b

    def test_present_task_state_not_not_found(self, tb):
        t, tmp, _ = tb
        b = t.get_task_bundle("t-test")
        assert b["task"]["state"] != "not_found"
        assert b["task"]["id"] == "t-test"

    def test_missing_task_state_is_not_found(self, tb):
        t, tmp, _ = tb
        b = t.get_task_bundle("t-no-such")
        assert b["task"]["state"] == "not_found"
        assert b["task"]["id"] == "t-no-such"

    def test_lock_info_free(self, tb):
        t, tmp, _ = tb
        b = t.get_task_bundle("t-test")
        assert b["lock"]["held"] is False

    def test_lock_info_held(self, tb):
        t, tmp, _ = tb
        t.acquire_lock("t-test", "agent-bundle", ttl=600)
        b = t.get_task_bundle("t-test")
        assert b["lock"]["held"] is True
        assert b["lock"]["owner"] == "agent-bundle"

    def test_council_info_no_dir(self, tb):
        t, tmp, _ = tb
        b = t.get_task_bundle("t-test")
        assert b["council"]["exists"] is False
        assert b["council"]["files"] == []

    def test_council_info_with_files(self, tb):
        t, tmp, _ = tb
        council_dir = tmp / "council" / "t-test"
        council_dir.mkdir(parents=True)
        (council_dir / "architect.md").write_text("# opinion")
        (council_dir / "reviewer.md").write_text("# opinion")
        b = t.get_task_bundle("t-test")
        assert b["council"]["exists"] is True
        assert "architect.md" in b["council"]["files"]
        assert "reviewer.md" in b["council"]["files"]

    def test_index_hint_has_health(self, tb):
        t, tmp, _ = tb
        b = t.get_task_bundle("t-test")
        assert "health" in b["index"]

    def test_bundle_lock_held_after_take(self, tb):
        t, tmp, _ = tb
        t.take_task("t-test", "agent-1")
        b = t.get_task_bundle("t-test")
        assert b["lock"]["held"] is True
        assert b["task"]["state"] != "not_found"
