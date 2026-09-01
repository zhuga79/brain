import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from brain_federation.sync import cmd_merge_tasks, cmd_sync, log_sync
from brain_federation import core as federation_core


@pytest.fixture(autouse=True)
def _isolate_node_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAIN_NODE_ID", raising=False)
    monkeypatch.delenv("BRAIN_NODE_ID_FROM_GIT", raising=False)
    federation_core._git_email_cache.clear()

class DummyArgs:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

def test_cmd_merge_tasks(tmp_path):
    base_file = tmp_path / "base.md"
    local_file = tmp_path / "local.md"
    remote_file = tmp_path / "remote.md"
    out_file = tmp_path / "out.md"
    
    base_text = "- [ ] [P1] t-1 — Base\n      role: dev\n      acceptance: A\n"
    local_text = "- [x] [P1] t-1 — Local\n      role: dev\n      acceptance: A\n"
    remote_text = "- [~] [P1] t-1 — Remote\n      role: dev\n      acceptance: A\n"
    
    base_file.write_text(base_text)
    local_file.write_text(local_text)
    remote_file.write_text(remote_text)
    
    args = DummyArgs(base=str(base_file), local=str(local_file), remote=str(remote_file), out=str(out_file))
    
    assert cmd_merge_tasks(args) == 0
    
    merged_text = out_file.read_text()
    assert "- [x] [P1] t-1 — Local" in merged_text

def test_cmd_merge_tasks_new_remote(tmp_path):
    base_file = tmp_path / "base.md"
    local_file = tmp_path / "local.md"
    remote_file = tmp_path / "remote.md"
    
    base_file.write_text("- [ ] [P1] t-1 — B\n      acceptance: A\n")
    # Add t-3 only in local (hit line 48: elif l:)
    local_file.write_text("- [ ] [P1] t-1 — B\n      acceptance: A\n- [ ] [P2] t-3 — LocalNew\n      acceptance: B\n")
    remote_file.write_text("- [ ] [P1] t-1 — B\n      acceptance: A\n- [ ] [P2] t-2 — New\n      acceptance: A\n")
    
    # Also add t-4 in BOTH local and remote, but NOT in base (hit line 44: if not b:)
    local_file.write_text(local_file.read_text() + "- [ ] [P1] t-4 — Both\n      acceptance: C\n")
    remote_file.write_text(remote_file.read_text() + "- [x] [P1] t-4 — Both\n      acceptance: C\n")
    
    args = DummyArgs(base=str(base_file), local=str(local_file), remote=str(remote_file), out="")
    
    # capturing stdout to check missing out arg
    import io
    import sys
    captured = io.StringIO()
    sys.stdout = captured
    assert cmd_merge_tasks(args) == 0
    sys.stdout = sys.__stdout__
    
    merged_text = captured.getvalue()
    assert "t-1" in merged_text
    assert "t-2" in merged_text

def test_cmd_merge_tasks_deleted_local(tmp_path):
    base_file = tmp_path / "base.md"
    local_file = tmp_path / "local.md"
    remote_file = tmp_path / "remote.md"
    out_file = tmp_path / "out.md"
    
    base_file.write_text("- [ ] [P1] t-1 — Base\n      acceptance: A\n")
    local_file.write_text("")  # Deleted locally
    remote_file.write_text("- [ ] [P1] t-1 — Base\n      acceptance: A\n") # Unchanged remotely
    
    args = DummyArgs(base=str(base_file), local=str(local_file), remote=str(remote_file), out=str(out_file))
    assert cmd_merge_tasks(args) == 0
    
    merged_text = out_file.read_text()
    assert "t-1" not in merged_text  # Should remain deleted since remote didn't change it

@patch("brain_federation.sync.is_git_repo")
def test_cmd_sync_not_repo(mock_is_git):
    mock_is_git.return_value = False
    args = DummyArgs(repo=".", json=False)
    assert cmd_sync(args) == 1

@patch("brain_federation.sync.is_git_repo")
@patch("brain_federation.sync.git_pull_rebase")
@patch("brain_federation.sync.git_push")
@patch("brain_federation.sync.log_sync")
def test_cmd_sync_success(mock_log, mock_push, mock_pull, mock_is_git, tmp_path):
    mock_is_git.return_value = True
    
    mock_pull_res = MagicMock()
    mock_pull_res.returncode = 0
    mock_pull.return_value = mock_pull_res
    
    mock_push_res = MagicMock()
    mock_push_res.returncode = 0
    mock_push.return_value = mock_push_res
    
    args = DummyArgs(repo=str(tmp_path), json=True)
    assert cmd_sync(args) == 0
    mock_log.assert_called_once()

@patch("brain_federation.sync.is_git_repo")
@patch("brain_federation.sync.git_pull_rebase")
@patch("brain_federation.sync.log_sync")
def test_cmd_sync_pull_fail(mock_log, mock_pull, mock_is_git, tmp_path):
    mock_is_git.return_value = True
    
    mock_pull_res = MagicMock()
    mock_pull_res.returncode = 1
    mock_pull_res.stderr = "Conflict"
    mock_pull.return_value = mock_pull_res
    
    args = DummyArgs(repo=str(tmp_path), json=True)
    assert cmd_sync(args) == 1
    assert mock_log.call_args[0][2] == "pull-failed"


@patch("brain_federation.sync.is_git_repo")
@patch("brain_federation.sync.git_pull_rebase")
@patch("brain_federation.sync.git_push")
@patch("brain_federation.sync.log_sync")
def test_cmd_sync_push_fail(mock_log, mock_push, mock_pull, mock_is_git, tmp_path):
    mock_is_git.return_value = True

    mock_pull_res = MagicMock()
    mock_pull_res.returncode = 0
    mock_pull.return_value = mock_pull_res

    mock_push_res = MagicMock()
    mock_push_res.returncode = 1
    mock_push_res.stderr = "Rejected"
    mock_push.return_value = mock_push_res

    args = DummyArgs(repo=str(tmp_path), json=True)
    assert cmd_sync(args) == 1
    assert mock_log.call_args[0][2] == "push-failed"


def test_cmd_sync_logs_node_audit_row(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_NODE_ID_FROM_GIT", "1")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "carol@example.org"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Carol"], check=True)

    args = DummyArgs(repo=str(tmp_path), brain=str(tmp_path), json=True)
    with patch("brain_federation.sync.git_pull_rebase") as mock_pull, \
         patch("brain_federation.sync.git_push") as mock_push:
        mock_pull.return_value = MagicMock(returncode=0)
        mock_push.return_value = MagicMock(returncode=0)
        assert cmd_sync(args) == 0

    log = tmp_path / "wiki" / "log.md"
    assert log.exists()
    content = log.read_text()
    assert "federation-sync |" in content
    assert "node=carol@example.org" in content
    assert "status=ok" in content


def test_cmd_sync_logs_node_audit_row_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_NODE_ID", "sync-env-node")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "carol@example.org"], check=True)

    args = DummyArgs(repo=str(tmp_path), brain=str(tmp_path), json=True)
    with patch("brain_federation.sync.git_pull_rebase") as mock_pull, \
         patch("brain_federation.sync.git_push") as mock_push:
        mock_pull.return_value = MagicMock(returncode=0)
        mock_push.return_value = MagicMock(returncode=0)
        assert cmd_sync(args) == 0

    log = tmp_path / "wiki" / "log.md"
    assert "node=sync-env-node" in log.read_text()


def test_cmd_sync_logs_anonymous_by_default(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "carol@example.org"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Carol"], check=True)

    args = DummyArgs(repo=str(tmp_path), brain=str(tmp_path), json=True)
    with patch("brain_federation.sync.git_pull_rebase") as mock_pull, \
         patch("brain_federation.sync.git_push") as mock_push:
        mock_pull.return_value = MagicMock(returncode=0)
        mock_push.return_value = MagicMock(returncode=0)
        assert cmd_sync(args) == 0

    content = (tmp_path / "wiki" / "log.md").read_text()
    assert "node=anonymous" in content
    assert "carol@example.org" not in content


def test_cmd_sync_invalid_node_blocks_without_writing_log(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_NODE_ID", "bad|pipe\n## [ts] task-done | t-fake | attacker")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    args = DummyArgs(repo=str(tmp_path), brain=str(tmp_path), json=True)
    with patch("brain_federation.sync.git_pull_rebase") as mock_pull, \
         patch("brain_federation.sync.git_push") as mock_push:
        assert cmd_sync(args) == 1
        mock_pull.assert_not_called()
        mock_push.assert_not_called()
    log = tmp_path / "wiki" / "log.md"
    assert not log.exists() or "federation-sync" not in log.read_text()
    assert not log.exists() or "t-fake" not in log.read_text()


def test_cmd_sync_invalid_config_node_emits_finding(tmp_path, capsys):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "federation.json").write_text(json.dumps({"node_id": "bad|node"}), encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    args = DummyArgs(repo=str(tmp_path), brain=str(tmp_path), json=True)
    assert cmd_sync(args) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False
    assert any(item["code"] == "federation-node-invalid" for item in data["findings"])
    log = tmp_path / "wiki" / "log.md"
    assert not log.exists() or "federation-sync" not in log.read_text()


def test_log_sync_uses_shared_journal_append_line(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_NODE_ID", "n1")
    with patch("brain_federation.sync.journal.append_line") as mock_append:
        log_sync(tmp_path, tmp_path, "ok")
    mock_append.assert_called_once()
    row, brain = mock_append.call_args.args
    assert brain == tmp_path
    assert "node=n1" in row
    assert "status=ok" in row
    assert row.endswith("\n")


def test_log_sync_places_node_in_extra_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_NODE_ID", "slot-node")
    log_sync(tmp_path, tmp_path, "ok")
    line = (tmp_path / "wiki" / "log.md").read_text().strip().splitlines()[-1]
    parts = line.split(" | ")
    assert parts[0].endswith("federation-sync")
    assert parts[2] == ""
    assert parts[3] == "node=slot-node"
    assert parts[4] == "status=ok"


def test_log_sync_rejects_injected_node(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "BRAIN_NODE_ID",
        "x\n## [2026-08-30T00:00:00Z] task-done | t-fake | attacker | model=x",
    )
    with pytest.raises(ValueError):
        log_sync(tmp_path, tmp_path, "ok")
    log = tmp_path / "wiki" / "log.md"
    if log.exists():
        text = log.read_text()
        assert "t-fake" not in text
        assert "attacker" not in text
        assert "task-done" not in text
