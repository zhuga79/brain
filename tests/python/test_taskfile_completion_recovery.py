from __future__ import annotations

from pathlib import Path

import pytest

from brain_core import taskfile


ACTIVE = """# Active Tasks

- [~] [P1] t-recover — Recoverable task
      role: developer   mode: solo
      acceptance: ok
      started: 2026-08-14T00:00:00Z
      by: owner-agent
"""


@pytest.fixture
def queue(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    active = tasks / "active.md"
    done = tasks / "done.md"
    active.write_text(ACTIVE, encoding="utf-8")
    done.write_text("# Done Tasks\n", encoding="utf-8")
    return active, done


def _count_done(done: Path, tid: str) -> int:
    return done.read_text(encoding="utf-8").count(f"{tid} —")


def test_complete_retry_after_crash_before_done_write(queue, monkeypatch):
    active, done = queue
    real_write = taskfile.atomic_write
    tripped = False

    def flaky_write(path: Path, text: str) -> None:
        nonlocal tripped
        if path == done and not tripped:
            tripped = True
            raise RuntimeError("boom-before-done")
        real_write(path, text)

    monkeypatch.setattr(taskfile, "atomic_write", flaky_write)

    with pytest.raises(RuntimeError, match="boom-before-done"):
        taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    journal = taskfile.complete_journal_path(active.parent, "t-recover")
    assert journal.is_file()
    assert "t-recover" in active.read_text(encoding="utf-8")
    assert _count_done(done, "t-recover") == 0

    monkeypatch.setattr(taskfile, "atomic_write", real_write)
    taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    assert "t-recover" not in active.read_text(encoding="utf-8")
    assert _count_done(done, "t-recover") == 1
    assert not journal.exists()


def test_complete_retry_after_crash_between_done_and_active(queue, monkeypatch):
    active, done = queue
    real_write = taskfile.atomic_write
    tripped = False

    def flaky_write(path: Path, text: str) -> None:
        nonlocal tripped
        real_write(path, text)
        if path == done and not tripped:
            tripped = True
            raise RuntimeError("boom-after-done")

    monkeypatch.setattr(taskfile, "atomic_write", flaky_write)

    with pytest.raises(RuntimeError, match="boom-after-done"):
        taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    journal = taskfile.complete_journal_path(active.parent, "t-recover")
    assert journal.is_file()
    assert "t-recover" in active.read_text(encoding="utf-8")
    assert _count_done(done, "t-recover") == 1

    monkeypatch.setattr(taskfile, "atomic_write", real_write)
    taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    assert "t-recover" not in active.read_text(encoding="utf-8")
    assert _count_done(done, "t-recover") == 1
    assert not journal.exists()


def test_complete_retry_after_crash_after_active_before_cleanup(queue, monkeypatch):
    active, done = queue
    real_cleanup = taskfile.cleanup_complete_journal
    tripped = False

    def flaky_cleanup(path: Path) -> None:
        nonlocal tripped
        if not tripped:
            tripped = True
            raise RuntimeError("boom-before-cleanup")
        real_cleanup(path)

    monkeypatch.setattr(taskfile, "cleanup_complete_journal", flaky_cleanup)

    with pytest.raises(RuntimeError, match="boom-before-cleanup"):
        taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    journal = taskfile.complete_journal_path(active.parent, "t-recover")
    assert journal.is_file()
    assert "t-recover" not in active.read_text(encoding="utf-8")
    assert _count_done(done, "t-recover") == 1

    monkeypatch.setattr(taskfile, "cleanup_complete_journal", real_cleanup)
    taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    assert "t-recover" not in active.read_text(encoding="utf-8")
    assert _count_done(done, "t-recover") == 1
    assert not journal.exists()


def test_complete_recovery_refuses_malformed_journal(queue):
    active, done = queue
    journal = taskfile.complete_journal_path(active.parent, "t-recover")
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("{bad json\n", encoding="utf-8")
    active_before = active.read_text(encoding="utf-8")
    done_before = done.read_text(encoding="utf-8")

    with pytest.raises(taskfile.TaskError, match="invalid completion journal"):
        taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    assert active.read_text(encoding="utf-8") == active_before
    assert done.read_text(encoding="utf-8") == done_before
    assert journal.is_file()


def test_complete_recovery_refuses_missing_task_in_both_files(queue):
    active, done = queue
    journal = taskfile.complete_journal_path(active.parent, "t-recover")
    journal.parent.mkdir(parents=True, exist_ok=True)
    taskfile.atomic_write(
        journal,
        '{"task_id":"t-recover","agent":"owner-agent","model":"openai-gpt-5.4","completed":"2026-08-14T00:00:00Z","entry":"- [x] [P1] t-recover — Recoverable task\\n"}\n',
    )
    taskfile.atomic_write(active, "# Active Tasks\n",)

    with pytest.raises(taskfile.TaskError, match="completion journal inconsistent"):
        taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    assert _count_done(done, "t-recover") == 0
    assert journal.is_file()
