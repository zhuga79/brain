import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from brain_federation.checks import (
    Finding,
    check_duplicates,
    check_cross_file_conflicts,
    check_runtime_paths,
    check_raw_rewrites,
    check_wiki_curation,
    check_provider_matrix,
    check_possible_secrets,
    check_optional_secret_scanner,
    check_gitignore,
    check_learning_status_conflict,
    check_council_synthesis_stale,
    comparable,
)

def test_comparable():
    t1 = {"title": "A", "role": "dev", "mode": "solo", "acceptance": "yes"}
    t2 = {"title": "A", "role": "dev", "mode": "solo", "acceptance": "yes", "extra": "ignored"}
    t3 = {"title": "B", "role": "dev", "mode": "solo", "acceptance": "yes"}
    
    assert comparable(t1) == ("A", "dev", "solo", "yes")
    assert comparable(t1) == comparable(t2)
    assert comparable(t1) != comparable(t3)

def test_check_duplicates():
    tasks = [
        {"id": "t1", "title": "A", "path": "p1", "line": 1},
        {"id": "t2", "title": "B", "path": "p1", "line": 10},
        {"id": "t1", "title": "A", "path": "p2", "line": 5}, # Duplicate, same
    ]
    findings = check_duplicates(tasks, "test-code")
    assert len(findings) == 1
    assert findings[0].code == "test-code"
    assert findings[0].path == "p2:5"
    assert "duplicate task id: t1" in findings[0].message

    tasks_conflict = [
        {"id": "t1", "title": "A", "path": "p1", "line": 1},
        {"id": "t1", "title": "B", "path": "p2", "line": 5}, # Duplicate, conflict
    ]
    findings = check_duplicates(tasks_conflict, "test-code")
    assert len(findings) == 2
    assert findings[1].code == "task-field-conflict"

def test_check_cross_file_conflicts():
    active = [{"id": "t1", "state": " ", "title": "A", "path": "a1", "line": 1}]
    done = [{"id": "t1", "state": "x", "title": "A", "path": "d1", "line": 5}]
    
    # Conflict: open in active, done in done
    findings = check_cross_file_conflicts(active, done)
    assert len(findings) == 1
    assert findings[0].code == "task-done-open-conflict"
    
    # Conflict: metadata
    active2 = [{"id": "t2", "state": " ", "title": "A", "path": "a1", "line": 1}]
    done2 = [{"id": "t2", "state": " ", "title": "B", "path": "d1", "line": 5}]
    findings = check_cross_file_conflicts(active2, done2)
    assert len(findings) == 1
    assert findings[0].code == "task-field-conflict"

def test_check_runtime_paths(tmp_path):
    (tmp_path / ".locks").mkdir()
    (tmp_path / "normal.md").write_text("ok")
    
    # Included in changed_paths but also exists
    findings = check_runtime_paths(tmp_path, {".locks/", "normal.md"})
    assert len(findings) == 1
    assert findings[0].code == "runtime-file-included"
    assert findings[0].path == ".locks"

def test_check_raw_rewrites():
    name_status = [
        ("M", "raw/source.md"),
        ("A", "raw/new.md"),
        ("D", "raw/old.md"),
        ("M", "wiki/page.md"),
    ]
    findings = check_raw_rewrites(name_status)
    assert len(findings) == 2
    assert findings[0].code == "raw-rewrite"
    assert findings[0].path == "raw/source.md"
    assert findings[1].path == "raw/old.md"

def test_check_wiki_curation(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "protected.md").write_text("---\nprotected: true\n---")
    (wiki / "human.md").write_text("---\ncuration: human\n---")
    (wiki / "normal.md").write_text("---\ntitle: normal\n---")
    
    changed = {"wiki/protected.md", "wiki/human.md", "wiki/normal.md", "other.txt"}
    findings = check_wiki_curation(tmp_path, changed)
    assert len(findings) == 2
    codes = [f.code for f in findings]
    assert "protected-wiki-edit" in codes
    assert "human-curated-wiki-edit" in codes

def test_check_provider_matrix(tmp_path):
    matrix_path = "wiki/provider-matrix.json"
    repo = tmp_path
    (repo / "wiki").mkdir()
    
    old_data = {"providers": {"p1": {"command": "cmd1"}}}
    new_data = {"providers": {"p1": {"command": "cmd2"}}}
    
    (repo / matrix_path).write_text(json.dumps(new_data))
    
    with patch("brain_federation.checks.git_show", return_value=json.dumps(old_data)):
        findings = check_provider_matrix(repo, {matrix_path})
        assert len(findings) == 2
        assert findings[0].code == "provider-matrix-change"
        assert findings[1].code == "provider-command-change"

def test_check_possible_secrets(tmp_path):
    mock_res = MagicMock()
    mock_res.stdout = "+ API_KEY = 'sk-1234567890abcdef'\n- old line"
    
    with patch("brain_federation.checks.git_run", return_value=mock_res):
        findings = check_possible_secrets(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "possible-secret"

def test_check_optional_secret_scanner(tmp_path):
    # Case: No command
    with patch.dict("os.environ", {"BRAIN_SECRET_SCANNER_CMD": ""}):
        assert check_optional_secret_scanner(tmp_path) == []
        
    # Case: Command works and returns JSON
    with patch.dict("os.environ", {"BRAIN_SECRET_SCANNER_CMD": "scanner"}):
        mock_run = MagicMock()
        mock_run.stdout = json.dumps({"code": "found-it", "severity": "block", "message": "msg"})
        mock_run.returncode = 0
        with patch("subprocess.run", return_value=mock_run):
            findings = check_optional_secret_scanner(tmp_path)
            assert len(findings) == 1
            assert findings[0].code == "found-it"
            assert findings[0].severity == "block"

def test_check_gitignore(tmp_path):
    # Case: missing .gitignore
    findings = check_gitignore(tmp_path)
    assert len(findings) == 1
    assert findings[0].code == "missing-generated-ignore"
    
    # Case: partial .gitignore
    (tmp_path / ".gitignore").write_text(".locks/\n")
    findings = check_gitignore(tmp_path)
    assert len(findings) == 1
    assert "missing: .brain/" in findings[0].hint

def test_check_learning_status_conflict(tmp_path):
    lessons = tmp_path / "learning" / "lessons"
    (lessons / "pending").mkdir(parents=True)
    (lessons / "approved").mkdir(parents=True)
    
    (lessons / "pending" / "les-1.md").write_text("...")
    (lessons / "approved" / "les-1.md").write_text("...")
    
    findings = check_learning_status_conflict(tmp_path)
    assert len(findings) == 1
    assert findings[0].code == "learning-status-conflict"
    assert "les-1" in findings[0].path

def test_check_council_synthesis_stale(tmp_path):
    council = tmp_path / "council" / "t1"
    council.mkdir(parents=True)
    
    syn = council / "synthesis.md"
    op = council / "architect.md"
    
    syn.write_text("old")
    import time
    time.sleep(0.01) # ensure mtime difference
    op.write_text("new")
    
    findings = check_council_synthesis_stale(tmp_path)
    assert len(findings) == 1
    assert findings[0].code == "council-synthesis-stale"

def test_check_cross_file_conflicts_no_match():
    active = [{"id": "t3", "state": " ", "title": "C", "path": "a1", "line": 10}]
    done = [{"id": "t1", "state": "x", "title": "A", "path": "d1", "line": 5}]
    assert check_cross_file_conflicts(active, done) == []

def test_check_runtime_paths_reported(tmp_path):
    (tmp_path / ".locks").mkdir()
    with patch("brain_federation.checks.RUNTIME_PATHS", (".locks/", ".locks/")):
        findings = check_runtime_paths(tmp_path, {".locks/"})
        assert len(findings) == 1


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _init_repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@test")
    _git(tmp_path, "config", "user.name", "t")


def test_check_runtime_paths_ignores_untracked_gitignored_dir(tmp_path):
    """A gitignored .locks/ that only exists on disk must not block preflight —
    every real vault has one."""
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text(".locks/\n.provider-health.json\n")
    (tmp_path / "keep.md").write_text("x\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    (tmp_path / ".locks" / "t-x").mkdir(parents=True)
    (tmp_path / ".locks" / "t-x" / "owner").write_text("agent\n")

    assert check_runtime_paths(tmp_path, set()) == []

    # ...but once it is staged for the sync, it is flagged again
    findings = check_runtime_paths(tmp_path, {".locks/t-x/owner"})
    assert [f.code for f in findings] == ["runtime-file-included"]


def test_check_runtime_paths_flags_tracked_runtime_file(tmp_path):
    """A runtime file force-committed despite .gitignore would reach a peer."""
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text(".provider-health.json\n")
    (tmp_path / ".provider-health.json").write_text("{}\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "add", "-f", ".provider-health.json")
    _git(tmp_path, "commit", "-qm", "oops")

    findings = check_runtime_paths(tmp_path, set())
    assert [f.code for f in findings] == ["runtime-file-included"]
    assert findings[0].path == ".provider-health.json"


def test_check_runtime_paths_flags_present_and_unignored(tmp_path):
    """Present on disk and NOT covered by .gitignore — a non-git import
    (rsync/tarball) would carry it."""
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text(".locks/\n")  # note: no .provider-health.json
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    (tmp_path / ".provider-health.json").write_text("{}\n")

    findings = check_runtime_paths(tmp_path, set())
    assert [f.code for f in findings] == ["runtime-file-included"]
    assert findings[0].path == ".provider-health.json"

def test_check_wiki_curation_no_fm(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "no_fm.md").write_text("no frontmatter")
    (wiki / "bad_fm.md").write_text("---\nbad line\n---")
    findings = check_wiki_curation(tmp_path, {"wiki/no_fm.md", "wiki/bad_fm.md"})
    assert findings == []

def test_check_optional_secret_scanner_errors(tmp_path):
    # Invalid command (shlex error)
    with patch.dict("os.environ", {"BRAIN_SECRET_SCANNER_CMD": "scanner 'unclosed"}):
        findings = check_optional_secret_scanner(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "secret-scanner-unavailable"

    # Timeout/OSError
    with patch.dict("os.environ", {"BRAIN_SECRET_SCANNER_CMD": "scanner"}):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["scanner"], 30)):
            findings = check_optional_secret_scanner(tmp_path)
            assert len(findings) == 1
            assert "timed out" in findings[0].message.lower()

    # OSError in _frontmatter
    with patch("pathlib.Path.read_text", side_effect=OSError("denied")):
        assert check_wiki_curation(tmp_path, {"wiki/p.md"}) == []

    # Non-JSON output
    with patch.dict("os.environ", {"BRAIN_SECRET_SCANNER_CMD": "scanner"}):
        mock_run = MagicMock()
        mock_run.stdout = "not json\n"
        mock_run.returncode = 0
        with patch("subprocess.run", return_value=mock_run):
            findings = check_optional_secret_scanner(tmp_path)
            assert len(findings) == 1
            assert findings[0].code == "secret-scanner-finding"

    # Bad exit code
    with patch.dict("os.environ", {"BRAIN_SECRET_SCANNER_CMD": "scanner"}):
        mock_run = MagicMock()
        mock_run.stdout = ""
        mock_run.returncode = 2
        with patch("subprocess.run", return_value=mock_run):
            findings = check_optional_secret_scanner(tmp_path)
            assert len(findings) == 1
            assert "exited 2" in findings[0].message
