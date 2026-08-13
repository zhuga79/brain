import os
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from brain_federation.sync import cmd_merge_tasks, cmd_sync

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
def test_cmd_sync_success(mock_push, mock_pull, mock_is_git):
    mock_is_git.return_value = True
    
    mock_pull_res = MagicMock()
    mock_pull_res.returncode = 0
    mock_pull.return_value = mock_pull_res
    
    mock_push_res = MagicMock()
    mock_push_res.returncode = 0
    mock_push.return_value = mock_push_res
    
    args = DummyArgs(repo=".", json=True)
    assert cmd_sync(args) == 0

@patch("brain_federation.sync.is_git_repo")
@patch("brain_federation.sync.git_pull_rebase")
def test_cmd_sync_pull_fail(mock_pull, mock_is_git):
    mock_is_git.return_value = True
    
    mock_pull_res = MagicMock()
    mock_pull_res.returncode = 1
    mock_pull_res.stderr = "Conflict"
    mock_pull.return_value = mock_pull_res
    
    args = DummyArgs(repo=".", json=True)
    assert cmd_sync(args) == 1

@patch("brain_federation.sync.is_git_repo")
@patch("brain_federation.sync.git_pull_rebase")
@patch("brain_federation.sync.git_push")
def test_cmd_sync_push_fail(mock_push, mock_pull, mock_is_git):
    mock_is_git.return_value = True
    
    mock_pull_res = MagicMock()
    mock_pull_res.returncode = 0
    mock_pull.return_value = mock_pull_res
    
    mock_push_res = MagicMock()
    mock_push_res.returncode = 1
    mock_push_res.stderr = "Rejected"
    mock_push.return_value = mock_push_res
    
    args = DummyArgs(repo=".", json=True)
    assert cmd_sync(args) == 1
