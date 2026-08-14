from __future__ import annotations

import json
import time
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
    lock_dir = tmp_path / ".locks" / "t-recover"
    tasks.mkdir()
    lock_dir.mkdir(parents=True)
    active = tasks / "active.md"
    done = tasks / "done.md"
    active.write_text(ACTIVE, encoding="utf-8")
    done.write_text("# Done Tasks\n", encoding="utf-8")
    owner = lock_dir / "owner"
    owner.write_text(f"owner-agent|{int(time.time())}|600\n", encoding="utf-8")
    return active, done, owner


def _count_done(done: Path, tid: str) -> int:
    return done.read_text(encoding="utf-8").count(f"{tid} —")


def _snapshot(*paths: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in paths}


def _assert_same(snapshot: dict[Path, bytes]) -> None:
    for path, before in snapshot.items():
        assert path.read_bytes() == before, path


def _current_block(active: Path, tid: str = "t-recover") -> str:
    active_text = active.read_text(encoding="utf-8")
    match = taskfile._any_state_pattern(tid).search(active_text)
    assert match
    return match.group(0)


def _journal_payload(
    active: Path,
    *,
    tid: str = "t-recover",
    owner: str = "owner-agent",
    model: str = "openai-gpt-5.4",
    completed: str = "2026-08-14T00:00:00Z",
    source_active: str | None = None,
) -> dict[str, str]:
    source = source_active if source_active is not None else _current_block(active, tid)
    entry = taskfile._build_done_entry(source, owner, model, completed)
    return {
        "version": taskfile.COMPLETE_JOURNAL_VERSION,
        "task_id": tid,
        "owner": owner,
        "model": model,
        "model_signature": taskfile._sha256_text(model),
        "completed": completed,
        "source_active": source,
        "source_active_fingerprint": taskfile._active_block_fingerprint(source),
        "final_entry_fingerprint": taskfile._entry_fingerprint(entry),
    }


def _write_journal(active: Path, payload: dict[str, str], *, tid: str = "t-recover") -> Path:
    journal = taskfile.complete_journal_path(active.parent, tid)
    taskfile.atomic.write_json(journal, payload)
    return journal


def test_complete_retry_after_crash_before_done_write(queue, monkeypatch):
    active, done, owner = queue
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
    assert owner.is_file()

    monkeypatch.setattr(taskfile, "atomic_write", real_write)
    taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    assert "t-recover" not in active.read_text(encoding="utf-8")
    assert _count_done(done, "t-recover") == 1
    assert not journal.exists()


def test_complete_retry_after_crash_between_done_and_active(queue, monkeypatch):
    active, done, owner = queue
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
    assert owner.is_file()

    monkeypatch.setattr(taskfile, "atomic_write", real_write)
    taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    assert "t-recover" not in active.read_text(encoding="utf-8")
    assert _count_done(done, "t-recover") == 1
    assert not journal.exists()


def test_complete_retry_after_crash_after_active_before_cleanup(queue, monkeypatch):
    active, done, owner = queue
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
    assert owner.is_file()

    monkeypatch.setattr(taskfile, "cleanup_complete_journal", real_cleanup)
    taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    assert "t-recover" not in active.read_text(encoding="utf-8")
    assert _count_done(done, "t-recover") == 1
    assert not journal.exists()


def test_complete_recovery_refuses_malformed_journal(queue):
    active, done, owner = queue
    journal = taskfile.complete_journal_path(active.parent, "t-recover")
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("{bad json\n", encoding="utf-8")
    before = _snapshot(active, done, owner, journal)

    with pytest.raises(taskfile.TaskError, match="invalid completion journal"):
        taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    _assert_same(before)


def test_complete_recovery_refuses_missing_task_in_both_files(queue):
    active, done, owner = queue
    journal = _write_journal(active, _journal_payload(active))
    taskfile.atomic_write(active, "# Active Tasks\n")
    before = _snapshot(active, done, owner, journal)

    with pytest.raises(taskfile.TaskError, match="completion journal inconsistent"):
        taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    _assert_same(before)


def test_complete_recovery_refuses_forged_intruder_journal(queue):
    active, done, owner = queue
    payload = _journal_payload(active, owner="intruder-agent", model="evil-model")
    journal = _write_journal(active, payload)
    before = _snapshot(active, done, owner, journal)

    with pytest.raises(taskfile.TaskError, match="task owned by owner-agent, not intruder-agent"):
        taskfile.complete(active, done, "t-recover", "intruder-agent", "evil-model")

    _assert_same(before)


@pytest.mark.parametrize(
    ("mutator", "error"),
    [
        (lambda payload: payload.update(owner="other-agent"), "completion journal owner mismatch: t-recover"),
        (lambda payload: payload.update(model="other-model"), "completion journal model mismatch: t-recover"),
        (
            lambda payload: payload.update(source_active_fingerprint="0" * 64),
            "invalid completion journal",
        ),
        (
            lambda payload: payload.update(final_entry_fingerprint="f" * 64),
            "invalid completion journal",
        ),
    ],
)
def test_complete_recovery_rejects_mismatched_journal_fields(queue, mutator, error):
    active, done, owner = queue
    payload = _journal_payload(active)
    mutator(payload)
    journal = _write_journal(active, payload)
    before = _snapshot(active, done, owner, journal)

    with pytest.raises(taskfile.TaskError, match=error):
        taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    _assert_same(before)


def test_complete_recovery_rejects_stale_source_fingerprint(queue):
    active, done, owner = queue
    payload = _journal_payload(active)
    journal = _write_journal(active, payload)
    active.write_text(
        ACTIVE.replace("acceptance: ok", "acceptance: changed"),
        encoding="utf-8",
    )
    before = _snapshot(active, done, owner, journal)

    with pytest.raises(taskfile.TaskError, match="completion journal fingerprint mismatch: t-recover"):
        taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    _assert_same(before)


def test_complete_recovery_rejects_done_entry_integrity_mismatch(queue):
    active, done, owner = queue
    payload = _journal_payload(active)
    expected_entry = taskfile._build_done_entry(
        payload["source_active"], payload["owner"], payload["model"], payload["completed"],
    )
    journal = _write_journal(active, payload)
    done.write_text("# Done Tasks\n\n" + expected_entry.replace("model: openai-gpt-5.4", "model: forged") + "\n", encoding="utf-8")
    before = _snapshot(active, done, owner, journal)

    with pytest.raises(taskfile.TaskError, match="completion journal entry mismatch: t-recover"):
        taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")

    _assert_same(before)


def test_complete_journal_path_rejects_task_id_path_traversal(queue):
    active, done, owner = queue
    before = _snapshot(active, done, owner)

    with pytest.raises(taskfile.TaskError, match=r"invalid task id: \.\./escape"):
        taskfile.complete(active, done, "../escape", "owner-agent", "openai-gpt-5.4")

    _assert_same(before)


def test_complete_journal_records_bound_fingerprints(queue):
    active, done, _owner = queue
    real_write = taskfile.atomic_write

    def flaky_write(path: Path, text: str) -> None:
        if path == done:
            raise RuntimeError("stop-after-journal")
        real_write(path, text)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(taskfile, "atomic_write", flaky_write)
    try:
        with pytest.raises(RuntimeError, match="stop-after-journal"):
            taskfile.complete(active, done, "t-recover", "owner-agent", "openai-gpt-5.4")
    finally:
        monkeypatch.undo()

    journal = taskfile.complete_journal_path(active.parent, "t-recover")
    payload = json.loads(journal.read_text(encoding="utf-8"))
    assert payload["owner"] == "owner-agent"
    assert payload["model"] == "openai-gpt-5.4"
    assert payload["model_signature"] == taskfile._sha256_text("openai-gpt-5.4")
    assert payload["source_active_fingerprint"] == taskfile._active_block_fingerprint(payload["source_active"])
    entry = taskfile._build_done_entry(
        payload["source_active"], payload["owner"], payload["model"], payload["completed"],
    )
    assert payload["final_entry_fingerprint"] == taskfile._entry_fingerprint(entry)
