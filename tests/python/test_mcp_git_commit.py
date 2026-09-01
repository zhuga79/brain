"""t-2026-08-14-autocommit-message-hygiene-do: the MCP auto-commit helper
commits only the files its operation touched — never an unrelated
uncommitted edit that happens to sit in the data layer.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "runtime" / "mcp"))
sys.path.insert(0, str(PROJECT_ROOT / "runtime" / "lib"))


def _stub_fastmcp(monkeypatch) -> None:
    fake_mcp_pkg = types.ModuleType("mcp")
    fake_mcp_server = types.ModuleType("mcp.server")
    fake_mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")
    fake_mcp_fastmcp.FastMCP = lambda *a, **k: MagicMock(tool=lambda: (lambda f: f))
    fake_mcp_pkg.server = fake_mcp_server
    fake_mcp_server.fastmcp = fake_mcp_fastmcp
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp_pkg)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_mcp_server)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_mcp_fastmcp)
    sys.modules.pop("common", None)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def brain_repo(tmp_path: Path) -> Path:
    brain = tmp_path / "brain"
    (brain / "tasks").mkdir(parents=True)
    (brain / "wiki").mkdir()
    (brain / "tasks" / "active.md").write_text("# Active\n", encoding="utf-8")
    (brain / "tasks" / "done.md").write_text("# Done\n", encoding="utf-8")
    (brain / "wiki" / "log.md").write_text("# Log\n", encoding="utf-8")
    _git(brain, "init", "-q")
    _git(brain, "config", "user.email", "t@t")
    _git(brain, "config", "user.name", "t")
    _git(brain, "add", "-A")
    _git(brain, "commit", "-qm", "base")
    return brain


@pytest.fixture
def git_commit(brain_repo, monkeypatch):
    monkeypatch.setenv("BRAIN_PATH", str(brain_repo))
    _stub_fastmcp(monkeypatch)
    import common

    monkeypatch.setattr(common, "BRAIN", brain_repo)
    return common.git_commit


def test_commit_is_scoped_to_named_paths(brain_repo, git_commit):
    (brain_repo / "tasks" / "active.md").write_text("# Active\n- [ ] t-1\n", encoding="utf-8")
    # an unrelated, uncommitted edit elsewhere in the data layer
    (brain_repo / "tasks" / "done.md").write_text("# Done\nstray edit\n", encoding="utf-8")

    git_commit("task-add: t-1", "tasks/active.md", "wiki/log.md")

    files = _git(brain_repo, "show", "--name-only", "--format=", "HEAD").split()
    assert "tasks/active.md" in files
    assert "tasks/done.md" not in files
    # the stray edit survives, still uncommitted
    assert "stray edit" in (brain_repo / "tasks" / "done.md").read_text(encoding="utf-8")
    assert _git(brain_repo, "status", "--porcelain", "tasks/done.md").strip()


def test_no_change_makes_no_commit(brain_repo, git_commit):
    head_before = _git(brain_repo, "rev-parse", "HEAD").strip()
    git_commit("task-add: t-noop", "tasks/active.md", "wiki/log.md")
    assert _git(brain_repo, "rev-parse", "HEAD").strip() == head_before


def test_default_paths_when_none_given(brain_repo, git_commit):
    (brain_repo / "wiki" / "log.md").write_text("# Log\nentry\n", encoding="utf-8")
    git_commit("task-done: t-2")
    files = _git(brain_repo, "show", "--name-only", "--format=", "HEAD").split()
    assert "wiki/log.md" in files


def test_subject_is_the_message_verbatim(brain_repo, git_commit):
    (brain_repo / "wiki" / "log.md").write_text("# Log\nx\n", encoding="utf-8")
    git_commit("council-start: t-3", "wiki/log.md")
    subject = _git(brain_repo, "log", "-1", "--format=%s").strip()
    assert subject == "council-start: t-3"
