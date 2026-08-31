"""t-2026-08-14-lock-ttl-versus-agent-task-dur: lease vs real agent work.

Default lock TTL used to be 600s. A typical agent task runs ~40 min, so
`brain-task complete` hit `task lock is stale` on live work, and the same
expiry made the task stealable while the first agent was still working.

The executor is often a subagent and cannot refresh: the caller holds the
lock. Tests here pin the replacement contract:

* default TTL covers a real agent-task duration (1 hour);
* the owner may still complete/release after expiry, as long as nobody else
  took the lock;
* expiry still frees abandoned work (takeover + cleanup).
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from brain_core import taskfile


ACTIVE = """# Active Tasks

- [~] [P1] t-ttl — Owned task
      role: developer   mode: solo
      acceptance: ok
      started: 2026-08-14T00:00:00Z
      by: owner-agent
"""

OPEN = """# Active Tasks

- [ ] [P1] t-ttl — Open task
      role: developer   mode: solo
      acceptance: ok
"""


def _queue(tmp_path: Path, text: str, lock: str | None) -> tuple[Path, Path, Path]:
    tasks = tmp_path / "tasks"
    tasks.mkdir(parents=True)
    active = tasks / "active.md"
    done = tasks / "done.md"
    active.write_text(text, encoding="utf-8")
    done.write_text("# Done Tasks\n", encoding="utf-8")
    if lock is not None:
        lock_dir = tmp_path / ".locks" / "t-ttl"
        lock_dir.mkdir(parents=True)
        (lock_dir / "owner").write_text(lock, encoding="utf-8")
    return tmp_path, active, done


def _owner_ttl(brain: Path, tid: str) -> int:
    raw = (brain / ".locks" / tid / "owner").read_text(encoding="utf-8").strip()
    return int(raw.split("|")[2])


class TestDefaultTtl:
    def test_default_ttl_covers_typical_agent_task(self):
        # 40 min observed; 10 min lease expired before complete.
        assert taskfile.LOCK_TTL_DEFAULT >= 3600

    def test_claim_lock_without_ttl_writes_the_default(self, tmp_path: Path):
        _brain, active, _done = _queue(tmp_path, OPEN, lock=None)
        taskfile.claim_lock(active, "t-ttl", "owner-agent")
        assert _owner_ttl(tmp_path, "t-ttl") == taskfile.LOCK_TTL_DEFAULT

    def test_take_without_ttl_writes_the_default(self, tmp_path: Path):
        _brain, active, _done = _queue(tmp_path, OPEN, lock=None)
        taskfile.take(active, "t-ttl", "owner-agent")
        assert _owner_ttl(tmp_path, "t-ttl") == taskfile.LOCK_TTL_DEFAULT


class TestOwnerFinishesAfterExpiry:
    def test_complete_allows_owner_on_stale_lock(self, tmp_path: Path):
        _brain, active, done = _queue(tmp_path, ACTIVE, lock="owner-agent|1|1\n")
        taskfile.complete(active, done, "t-ttl", "owner-agent", "good-model")
        assert "t-ttl" not in active.read_text(encoding="utf-8")
        done_text = done.read_text(encoding="utf-8")
        assert "t-ttl" in done_text
        assert "model: good-model" in done_text

    def test_release_allows_owner_on_stale_lock(self, tmp_path: Path):
        _brain, active, _done = _queue(tmp_path, ACTIVE, lock="owner-agent|1|1\n")
        taskfile.release(active, "t-ttl", "owner-agent")
        text = active.read_text(encoding="utf-8")
        assert "- [ ] [P1] t-ttl" in text
        assert "by: owner-agent" not in text

    def test_block_allows_owner_on_stale_lock(self, tmp_path: Path):
        _brain, active, _done = _queue(tmp_path, ACTIVE, lock="owner-agent|1|1\n")
        taskfile.block(active, "t-ttl", "owner-agent")
        assert "- [!] [P1] t-ttl" in active.read_text(encoding="utf-8")

    def test_complete_rejects_owner_after_stale_takeover(self, tmp_path: Path):
        _brain, active, done = _queue(tmp_path, ACTIVE, lock="owner-agent|1|1\n")
        taskfile.claim_lock(active, "t-ttl", "next-agent", ttl=60)
        before_active = active.read_bytes()
        before_done = done.read_bytes()
        with pytest.raises(taskfile.TaskError, match="lock owned by next-agent, not owner-agent"):
            taskfile.complete(active, done, "t-ttl", "owner-agent", "good-model")
        assert active.read_bytes() == before_active
        assert done.read_bytes() == before_done


class TestExpiryStillFreesAbandonedWork:
    def test_claim_lock_takes_over_stale_lock(self, tmp_path: Path):
        _brain, active, _done = _queue(tmp_path, OPEN, lock="dead-agent|1|1\n")
        taskfile.claim_lock(active, "t-ttl", "next-agent", ttl=60)
        owner = (tmp_path / ".locks" / "t-ttl" / "owner").read_text(encoding="utf-8")
        assert owner.startswith("next-agent|")

    def test_live_lock_is_not_taken_over(self, tmp_path: Path):
        stamp = f"owner-agent|{int(time.time())}|600\n"
        _brain, active, _done = _queue(tmp_path, OPEN, lock=stamp)
        with pytest.raises(taskfile.TaskError, match="locked by owner-agent"):
            taskfile.claim_lock(active, "t-ttl", "next-agent", ttl=60)
        owner = (tmp_path / ".locks" / "t-ttl" / "owner").read_text(encoding="utf-8")
        assert owner == stamp

    def test_reconcile_fix_still_frees_stale_in_progress_lock(self, tmp_path: Path):
        _brain, active, _done = _queue(tmp_path, ACTIVE, lock="owner-agent|1|1\n")
        findings = taskfile.reconcile_locks(active, fix=True)
        assert [f["kind"] for f in findings] == ["lock_stale"]
        assert "- [ ] [P1] t-ttl" in active.read_text(encoding="utf-8")
        assert not (tmp_path / ".locks" / "t-ttl").exists()
