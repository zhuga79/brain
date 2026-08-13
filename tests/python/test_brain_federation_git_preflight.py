import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import argparse
from brain_federation.git_ops import (
    git_run,
    is_git_repo,
    git_paths,
    git_name_status,
    git_show,
    git_head,
    frontmatter,
    path_matches,
)
from brain_federation.preflight import (
    parse_task_file_optional,
    collect_preflight,
    cmd_preflight,
)

# --- Git Ops Tests ---

def test_git_run(tmp_path):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(["git"], 0, "out", "err")
        res = git_run(tmp_path, "status")
        assert res.stdout == "out"
        mock_run.assert_called_once()

def test_is_git_repo(tmp_path):
    with patch("brain_federation.git_ops.git_run") as mock_git:
        # Case: True
        mock_git.return_value = subprocess.CompletedProcess([], 0, "true\n", "")
        assert is_git_repo(tmp_path) is True
        
        # Case: False
        mock_git.return_value = subprocess.CompletedProcess([], 1, "false\n", "")
        assert is_git_repo(tmp_path) is False

def test_git_paths(tmp_path):
    with patch("brain_federation.git_ops.git_run") as mock_git:
        def side_effect(repo, *args):
            if args[0] == "status":
                return subprocess.CompletedProcess([], 0, " M file1.md\n R old.md -> new.md\n?? untracked.txt\n", "")
            if args[0] == "diff":
                return subprocess.CompletedProcess([], 0, "file1.md\ndiff_only.md\n", "")
            return subprocess.CompletedProcess([], 0, "", "")
        
        mock_git.side_effect = side_effect
        paths = git_paths(tmp_path)
        assert "file1.md" in paths
        assert "old.md" in paths
        assert "new.md" in paths
        assert "untracked.txt" in paths
        assert "diff_only.md" in paths

def test_git_name_status(tmp_path):
    with patch("brain_federation.git_ops.git_run") as mock_git:
        mock_git.return_value = subprocess.CompletedProcess([], 0, "M\tfile1.md\nA\tfile2.md\n", "")
        entries = git_name_status(tmp_path)
        assert entries == [("M", "file1.md"), ("A", "file2.md")]

def test_git_show(tmp_path):
    with patch("brain_federation.git_ops.git_run") as mock_git:
        # Success
        mock_git.return_value = subprocess.CompletedProcess([], 0, "content", "")
        assert git_show(tmp_path, "file") == "content"
        
        # Failure
        mock_git.return_value = subprocess.CompletedProcess([], 1, "", "error")
        assert git_show(tmp_path, "file") is None

def test_git_head(tmp_path):
    with patch("brain_federation.git_ops.is_git_repo", return_value=True):
        with patch("brain_federation.git_ops.git_run") as mock_git:
            mock_git.return_value = subprocess.CompletedProcess([], 0, "abcdef\n", "")
            assert git_head(tmp_path) == "abcdef"
    
    with patch("brain_federation.git_ops.is_git_repo", return_value=False):
        assert git_head(tmp_path) == ""

def test_git_ops_frontmatter(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("---\ntitle: T\n---\nbody")
    assert frontmatter(f) == {"title": "t"}
    
    # Missing/invalid
    f2 = tmp_path / "missing.md"
    assert frontmatter(f2) == {}
    
    f3 = tmp_path / "no_fm.md"
    f3.write_text("no frontmatter")
    assert frontmatter(f3) == {}

def test_path_matches():
    assert path_matches("a/b", "a/") is True
    assert path_matches("a", "a/") is True
    assert path_matches("b", "a/") is False
    assert path_matches("a/b", "a/b") is True
    assert path_matches("a/c", "a/b") is False

# --- Preflight Tests ---

def test_parse_task_file_optional(tmp_path):
    f = tmp_path / "tasks.md"
    # Not exists
    assert parse_task_file_optional(f, "src") == ([], [])
    
    # Exists
    f.write_text("- [ ] t1 — Task")
    with patch("brain_federation.preflight.parse_task_file", return_value=([{"id": "t1"}], [])) as mock_p:
        tasks, findings = parse_task_file_optional(f, "src")
        assert tasks == [{"id": "t1"}]
        mock_p.assert_called_once()

def test_collect_preflight(tmp_path):
    brain = tmp_path / "brain"
    brain.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    
    # Case: Inside Git
    with patch("brain_federation.preflight.is_git_repo", return_value=True):
        with patch("brain_federation.preflight.git_paths", return_value={"p1"}):
            with patch("brain_federation.preflight.git_name_status", return_value=[("M", "p1")]):
                data, findings, changed = collect_preflight(repo, brain)
                assert changed == {"p1"}
                assert data["ok"] is True

    # Case: Outside Git
    with patch("brain_federation.preflight.is_git_repo", return_value=False):
        data, findings, changed = collect_preflight(repo, brain)
        assert changed == set()
        assert any(f.code == "outside-git-repo" for f in findings)

    # Case: Error
    with pytest.raises(FileNotFoundError):
        collect_preflight(Path("/non/existent"), brain)

def test_cmd_preflight(tmp_path):
    args = argparse.Namespace(repo=str(tmp_path), brain=None, json=True)
    
    with patch("brain_federation.preflight.collect_preflight") as mock_collect:
        mock_collect.return_value = ({"ok": True}, [], {"p1"})
        with patch("brain_federation.preflight.emit") as mock_emit:
            assert cmd_preflight(args) == 0
            mock_emit.assert_called_once()
            
    # Case: Error
    with patch("brain_federation.preflight.collect_preflight", side_effect=FileNotFoundError("err")):
        assert cmd_preflight(args) == 2
