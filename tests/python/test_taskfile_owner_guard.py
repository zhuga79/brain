from __future__ import annotations

import time
from pathlib import Path

import pytest

from brain_core import taskfile


ACTIVE = """# Active Tasks

- [~] [P1] t-owner-guard — Owned task
      role: developer   mode: solo
      acceptance: ok
      started: 2026-08-14T00:00:00Z
      by: owner-agent
"""


@pytest.fixture
def queue(tmp_path: Path):
    tasks = tmp_path / "tasks"
    locks = tmp_path / ".locks" / "t-owner-guard"
    tasks.mkdir()
    locks.mkdir(parents=True)
    active = tasks / "active.md"
    done = tasks / "done.md"
    active.write_text(ACTIVE, encoding="utf-8")
    done.write_text("# Done Tasks\n", encoding="utf-8")
    (locks / "owner").write_text(f"owner-agent|{int(time.time())}|600\n", encoding="utf-8")
    return tmp_path, active, done, locks / "owner"


def _snapshot(*paths: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in paths}


def _assert_same(snapshot: dict[Path, bytes]) -> None:
    for path, before in snapshot.items():
        assert path.read_bytes() == before, path


def test_release_rejects_wrong_owner_before_write(queue):
    _brain, active, done, owner = queue
    before = _snapshot(active, done, owner)
    with pytest.raises(taskfile.TaskError, match="task owned by owner-agent, not intruder"):
        taskfile.release(active, "t-owner-guard", "intruder")
    _assert_same(before)


def test_block_rejects_wrong_owner_before_write(queue):
    _brain, active, done, owner = queue
    before = _snapshot(active, done, owner)
    with pytest.raises(taskfile.TaskError, match="task owned by owner-agent, not intruder"):
        taskfile.block(active, "t-owner-guard", "intruder")
    _assert_same(before)


def test_complete_rejects_wrong_owner_before_write(queue):
    _brain, active, done, owner = queue
    before = _snapshot(active, done, owner)
    with pytest.raises(taskfile.TaskError, match="task owned by owner-agent, not intruder"):
        taskfile.complete(active, done, "t-owner-guard", "intruder", "evil-model")
    _assert_same(before)


def test_complete_rejects_stale_lock_before_write(queue):
    _brain, active, done, owner = queue
    owner.write_text("owner-agent|1|1\n", encoding="utf-8")
    before = _snapshot(active, done, owner)
    with pytest.raises(taskfile.TaskError, match="task lock is stale: t-owner-guard"):
        taskfile.complete(active, done, "t-owner-guard", "owner-agent", "good-model")
    _assert_same(before)


def test_owner_happy_path_mutates_only_active_and_done(queue):
    _brain, active, done, owner = queue
    owner_before = owner.read_bytes()
    taskfile.complete(active, done, "t-owner-guard", "owner-agent", "good-model")
    assert "t-owner-guard" not in active.read_text(encoding="utf-8")
    done_text = done.read_text(encoding="utf-8")
    assert "t-owner-guard" in done_text
    assert "model: good-model" in done_text
    assert owner.read_bytes() == owner_before
