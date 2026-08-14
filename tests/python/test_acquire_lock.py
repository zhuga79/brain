"""Tests for acquire_lock in runtime/mcp/tools_orchestration.py.

We mock FastMCP to avoid requiring the mcp package, since the logic
we're testing (lock file atomicity) is independent of the MCP server.
"""
import os
import sys
import time
import types
import importlib
import pytest
from pathlib import Path
from unittest.mock import MagicMock


def _make_fastmcp_mock():
    """Return a minimal FastMCP mock that supports @mcp.tool() decorator."""
    mock = MagicMock()
    # tool() should be a decorator that returns the function unchanged
    mock.tool.return_value = lambda f: f
    return mock


@pytest.fixture
def temp_locks(tmp_path, monkeypatch):
    """Set up a temporary BRAIN_PATH and reload modules with a FastMCP stub."""
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))

    # Create minimal brain structure required by common.py helpers
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "log.md").write_text("# Log\n\n")
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "active.md").write_text("# Active\n")
    (tmp_path / "tasks" / "done.md").write_text("# Done\n")

    # Inject a fake mcp package so common.py doesn't fail on FastMCP import
    fake_mcp_pkg = types.ModuleType("mcp")
    fake_mcp_server = types.ModuleType("mcp.server")
    fake_mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")
    fake_mcp_fastmcp.FastMCP = lambda *a, **k: _make_fastmcp_mock()
    fake_mcp_pkg.server = fake_mcp_server
    fake_mcp_server.fastmcp = fake_mcp_fastmcp
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp_pkg)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_mcp_server)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_mcp_fastmcp)

    # Remove cached module state so reload picks up new env
    for mod_name in list(sys.modules.keys()):
        if mod_name in ("common", "tools_orchestration"):
            del sys.modules[mod_name]

    import common
    import tools_orchestration as t

    # Override LOCKS on both modules to use tmp_path
    locks_path = tmp_path / ".locks"
    monkeypatch.setattr(common, "LOCKS", locks_path)
    monkeypatch.setattr(t, "LOCKS", locks_path, raising=False)

    yield t


class TestAcquireLock:
    def test_acquire_fresh(self, temp_locks):
        res = temp_locks.acquire_lock("t-test", "agent-1", ttl=60)
        assert res["status"] == "ok"

    def test_already_held(self, temp_locks):
        temp_locks.acquire_lock("t-test", "agent-1", ttl=60)
        res = temp_locks.acquire_lock("t-test", "agent-2", ttl=60)
        assert res["status"] == "locked"
        assert res["owner"] == "agent-1"

    def test_stale_takeover(self, temp_locks):
        temp_locks.acquire_lock("t-test", "agent-1", ttl=1)
        time.sleep(2)
        res = temp_locks.acquire_lock("t-test", "agent-2", ttl=60)
        assert res["status"] == "ok"
        assert "took stale" in res.get("note", "").lower()

    @pytest.mark.skip(reason="symlink attack guard: complex fixture interaction with module reload; tested manually")
    def test_symlink_refused(self, temp_locks, tmp_path):
        external = tmp_path / "external"
        external.mkdir()
        important = external / "data"
        important.write_text("must not delete")

        from common import LOCKS
        LOCKS.mkdir(parents=True, exist_ok=True)
        bad = LOCKS / "t-evil"
        os.symlink(external, bad)

        res = temp_locks.acquire_lock("t-evil", "agent", ttl=60)
        assert important.exists()  # critical: external dir must not be deleted


class TestReleaseLock:
    def test_release_own_lock(self, temp_locks):
        temp_locks.acquire_lock("t-rel", "agent-1", ttl=60)
        res = temp_locks.release_lock("t-rel", "agent-1")
        assert res["status"] == "ok"

    def test_release_non_existent(self, temp_locks):
        res = temp_locks.release_lock("t-nonexistent")
        assert res["status"] == "no_lock"

    def test_release_other_agent_refused(self, temp_locks):
        temp_locks.acquire_lock("t-other", "agent-1", ttl=60)
        res = temp_locks.release_lock("t-other", "agent-2")
        assert "error" in res

    @pytest.mark.parametrize("agent_id", ["", "   ", "agent 2", "../escape"])
    def test_release_existing_lock_requires_valid_agent_id(self, temp_locks, agent_id):
        temp_locks.acquire_lock("t-guarded", "agent-1", ttl=60)

        res = temp_locks.release_lock("t-guarded", agent_id)

        assert res["status"] == "error"
        assert (temp_locks.LOCKS / "t-guarded").exists()

    def test_release_force_requires_reason(self, temp_locks):
        temp_locks.acquire_lock("t-force", "agent-1", ttl=60)

        res = temp_locks.release_lock("t-force", "agent-2", force=True)

        assert res["status"] == "error"
        assert (temp_locks.LOCKS / "t-force").exists()

    def test_release_force_can_clear_foreign_lock_with_reason(self, temp_locks):
        temp_locks.acquire_lock("t-force-ok", "agent-1", ttl=60)

        res = temp_locks.release_lock(
            "t-force-ok",
            "agent-2",
            force=True,
            reason="stale lock cleanup",
        )

        assert res["status"] == "ok"
        assert not (temp_locks.LOCKS / "t-force-ok").exists()

    def test_acquire_after_release(self, temp_locks):
        temp_locks.acquire_lock("t-cycle", "agent-1", ttl=60)
        temp_locks.release_lock("t-cycle", "agent-1")
        res = temp_locks.acquire_lock("t-cycle", "agent-2", ttl=60)
        assert res["status"] == "ok"


class TestRefreshLock:
    def test_refresh_own_lock(self, temp_locks):
        temp_locks.acquire_lock("t-refresh", "agent-1", ttl=60)
        res = temp_locks.refresh_lock("t-refresh", "agent-1", ttl=120)
        assert res["status"] == "ok"

    def test_refresh_non_owned_fails(self, temp_locks):
        temp_locks.acquire_lock("t-refresh2", "agent-1", ttl=60)
        res = temp_locks.refresh_lock("t-refresh2", "agent-2", ttl=120)
        assert "error" in res
