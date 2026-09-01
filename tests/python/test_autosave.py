"""t-2026-08-16-autosave-uncommitted-agent-wor.

An executor that dies mid-task leaves uncommitted work in its worktree. When
the stale lock is evicted the work must be findable afterwards — pinned under
a tag, its path written into the task's ``resume:`` field — without the
executor's working tree or index being touched.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from brain_core import autosave, taskfile

_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(wt: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(wt), *args],
        capture_output=True, text=True, env=_GIT_ENV, check=False,
    )


@pytest.fixture(autouse=True)
def _enable_autosave(monkeypatch):
    """conftest disables autosave for every test; this module tests it, so
    turn it back on (and keep BRAIN_TEST_SANDBOX clear except where a test
    sets it back)."""
    monkeypatch.delenv("BRAIN_AUTOSAVE_DISABLE", raising=False)
    monkeypatch.delenv("BRAIN_TEST_SANDBOX", raising=False)


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    (root / "tasks").mkdir(parents=True)
    (root / ".locks").mkdir()
    (root / "tasks" / "active.md").write_text(
        "# Active Tasks\n\n"
        "- [~] [P1] t-job — Do the job\n"
        "      role: developer   mode: solo\n"
        "      acceptance: done.\n"
        "      by: dead-agent\n"
        "      started: 2026-08-01T00:00:00Z\n"
        "      ttl: 1\n\n",
        encoding="utf-8",
    )
    (root / "tasks" / "done.md").write_text("# Done tasks\n\n", encoding="utf-8")
    return root


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    wt = tmp_path / "wt"
    wt.mkdir()
    _git(wt, "init", "-q", "-b", "main")
    _git(wt, "config", "user.email", "t@t")
    _git(wt, "config", "user.name", "t")
    (wt / "impl.py").write_text("original\n", encoding="utf-8")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-qm", "base")
    return wt


def _locks(root: Path) -> Path:
    return root / ".locks"


def _active(root: Path) -> Path:
    return root / "tasks" / "active.md"


def _dirty(wt: Path) -> None:
    (wt / "impl.py").write_text("half-finished work\n", encoding="utf-8")
    (wt / "brand_new.py").write_text("def f(): pass\n", encoding="utf-8")


def test_record_worktree_stores_git_toplevel(data_root, worktree):
    sub = worktree / "pkg"
    sub.mkdir()
    autosave.record_worktree(_locks(data_root), "t-job", sub)
    stored = (_locks(data_root) / "t-job.worktree").read_text().strip()
    assert Path(stored) == worktree.resolve()


def test_non_git_cwd_records_nothing(data_root, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert autosave.record_worktree(_locks(data_root), "t-job", plain) is None
    assert not (_locks(data_root) / "t-job.worktree").exists()


def test_clean_tree_saves_nothing(data_root, worktree):
    (_locks(data_root) / "t-job").mkdir()
    autosave.record_worktree(_locks(data_root), "t-job", worktree)
    assert autosave.autosave(_locks(data_root), "t-job") is None


def test_dirty_tree_is_snapshotted_tracked_and_untracked(data_root, worktree):
    (_locks(data_root) / "t-job").mkdir()
    autosave.record_worktree(_locks(data_root), "t-job", worktree)
    _dirty(worktree)

    tag = autosave.autosave(_locks(data_root), "t-job", agent="dead-agent")
    assert tag == "wip-recovery/t-job"

    assert _git(worktree, "show", f"{tag}:impl.py").stdout == "half-finished work\n"
    assert _git(worktree, "show", f"{tag}:brand_new.py").stdout == "def f(): pass\n"


def test_snapshot_does_not_touch_working_tree_or_index(data_root, worktree):
    (_locks(data_root) / "t-job").mkdir()
    autosave.record_worktree(_locks(data_root), "t-job", worktree)
    (worktree / "impl.py").write_text("wip\n", encoding="utf-8")
    (worktree / "extra").write_text("x\n", encoding="utf-8")
    _git(worktree, "add", "impl.py")  # stage one change

    autosave.autosave(_locks(data_root), "t-job")

    assert (worktree / "impl.py").read_text() == "wip\n"
    assert (worktree / "extra").exists()
    status = _git(worktree, "status", "--porcelain").stdout
    assert "M  impl.py" in status  # still staged
    assert "?? extra" in status  # still untracked


def test_idempotent_same_content_no_duplicate_tag(data_root, worktree):
    (_locks(data_root) / "t-job").mkdir()
    autosave.record_worktree(_locks(data_root), "t-job", worktree)
    _dirty(worktree)

    first = autosave.autosave(_locks(data_root), "t-job")
    second = autosave.autosave(_locks(data_root), "t-job")
    assert first == second == "wip-recovery/t-job"
    tags = _git(worktree, "tag", "-l", "wip-recovery/*").stdout.split()
    assert tags == ["wip-recovery/t-job"]


def test_second_interruption_different_content_does_not_clobber(data_root, worktree):
    (_locks(data_root) / "t-job").mkdir()
    autosave.record_worktree(_locks(data_root), "t-job", worktree)

    (worktree / "impl.py").write_text("attempt one\n", encoding="utf-8")
    tag1 = autosave.autosave(_locks(data_root), "t-job")
    (worktree / "impl.py").write_text("attempt two\n", encoding="utf-8")
    tag2 = autosave.autosave(_locks(data_root), "t-job")

    assert tag1 == "wip-recovery/t-job"
    assert tag2 == "wip-recovery/t-job-2"
    assert _git(worktree, "show", f"{tag1}:impl.py").stdout == "attempt one\n"
    assert _git(worktree, "show", f"{tag2}:impl.py").stdout == "attempt two\n"


def test_survives_worktree_removal(data_root, worktree, tmp_path):
    """The tag lives in the repo's object store, not the worktree dir."""
    import shutil

    (_locks(data_root) / "t-job").mkdir()
    autosave.record_worktree(_locks(data_root), "t-job", worktree)
    _dirty(worktree)
    autosave.autosave(_locks(data_root), "t-job")

    # git worktree layout: a linked worktree keeps objects in the main repo.
    # Here `worktree` IS the repo, so removing it removes everything — instead
    # assert the tag object is reachable without the working files present.
    _git(worktree, "reset", "--hard", "HEAD")  # wipe uncommitted work
    _git(worktree, "clean", "-fdx")
    assert not (worktree / "brand_new.py").exists()
    assert _git(worktree, "show", "wip-recovery/t-job:brand_new.py").stdout == "def f(): pass\n"


def test_flush_breadcrumb_writes_resume_field(data_root, worktree):
    (_locks(data_root) / "t-job").mkdir()
    autosave.record_worktree(_locks(data_root), "t-job", worktree)
    _dirty(worktree)
    autosave.autosave(_locks(data_root), "t-job")

    tag = autosave.flush_breadcrumb(_locks(data_root), _active(data_root), "t-job")
    assert tag == "wip-recovery/t-job"

    text = _active(data_root).read_text()
    assert "resume: WIP предыдущего исполнителя автосохранён" in text
    assert "git cherry-pick -n wip-recovery/t-job" in text
    assert not (_locks(data_root) / "t-job.autosaved").exists()  # cleared


def test_annotate_resume_replaces_not_appends(data_root):
    active = _active(data_root)
    taskfile.annotate_resume(active, "t-job", "first note")
    taskfile.annotate_resume(active, "t-job", "second note")
    text = active.read_text()
    assert text.count("resume:") == 1
    assert "second note" in text
    assert "first note" not in text


def test_reconcile_fix_autosaves_stale_lock(data_root, worktree):
    """End-to-end: stale [~] lock + dirty worktree -> reconcile --fix saves it
    and the queue's resume: field points at the tag."""
    active = _active(data_root)
    tid = "t-job"
    # taskfile lock owner format is agent|epoch|ttl; make it stale.
    lock = _locks(data_root) / tid
    lock.mkdir()
    (lock / "owner").write_text(f"dead-agent|{int(time.time()) - 10}|1\n", encoding="utf-8")
    autosave.record_worktree(_locks(data_root), tid, worktree)
    _dirty(worktree)

    findings = taskfile.reconcile_locks(active, fix=True)
    stale = [f for f in findings if f["id"] == tid]
    assert stale and stale[0]["fixed"]
    assert stale[0].get("autosaved") == "wip-recovery/t-job"

    text = active.read_text()
    assert "- [ ] [P1] t-job" in text  # returned to open
    assert "resume: WIP предыдущего исполнителя автосохранён" in text
    assert _git(worktree, "show", "wip-recovery/t-job:brand_new.py").stdout == "def f(): pass\n"


def test_autosave_never_raises_on_broken_worktree(data_root):
    (_locks(data_root) / "t-job").mkdir()
    (_locks(data_root) / "t-job.worktree").write_text("/nonexistent/path\n", encoding="utf-8")
    assert autosave.autosave(_locks(data_root), "t-job") is None
    assert autosave.evict(_locks(data_root), _active(data_root), "t-job") is None


def test_skipped_under_test_sandbox(data_root, worktree, monkeypatch):
    """The smoke runner sets BRAIN_TEST_SANDBOX; autosave must not tag the live
    checkout it happens to be run from."""
    monkeypatch.setenv("BRAIN_TEST_SANDBOX", "1")
    autosave.record_worktree(_locks(data_root), "t-job", worktree)
    _dirty(worktree)
    assert autosave.autosave(_locks(data_root), "t-job") is None
    assert not (_locks(data_root) / "t-job.worktree").exists()
    assert _git(worktree, "tag", "-l", "wip-recovery/*").stdout.strip() == ""
