"""Tests for brain_launch_watch.run_watch_loop.

All tests use injectable helpers so no real brain-* commands are invoked.
"""
from __future__ import annotations

import sys
import types
import pytest
from pathlib import Path
from unittest.mock import MagicMock, call


REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "runtime" / "lib"))

from brain_launch_watch import run_watch_loop  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockProc:
    """Minimal fake Popen return value."""
    def __init__(self, returncode: int = 0):
        self.pid = 99999
        self.returncode = returncode

    def poll(self):
        return self.returncode


def _make_helpers(
    *,
    task_sequence=None,       # list of task ids per _next call (None = empty)
    take_results=None,        # list of bool per _take call
    done_after_n_polls=1,     # after how many polls _done returns True
    sleep_limit=None,         # max times _sleep is allowed to be called
):
    """Return a dict of injectable helpers with controllable behaviour."""
    task_iter = iter(task_sequence or [])
    take_iter = iter(take_results or [])
    poll_counts: dict = {}

    def _next(role):
        try:
            return next(task_iter)
        except StopIteration:
            return None

    def _take(tid, aid):
        try:
            return next(take_iter)
        except StopIteration:
            return True  # default: success

    def _release(tid, aid):
        pass

    proc = _MockProc()

    def _launch(tid):
        return proc

    poll_counter = {"n": 0}

    def _done(tid):
        poll_counter["n"] += 1
        return poll_counter["n"] >= done_after_n_polls

    sleep_counter = {"n": 0}
    sleep_limit_val = sleep_limit

    def _sleep(secs):
        sleep_counter["n"] += 1
        if sleep_limit_val is not None and sleep_counter["n"] > sleep_limit_val:
            raise RuntimeError(f"_sleep called more than {sleep_limit_val} times")

    messages: list[str] = []

    def _print(msg):
        messages.append(msg)

    log_entries: list[tuple] = []

    def _log(op, tid, aid, extra):
        log_entries.append((op, tid, aid, extra))

    return {
        "next_task_fn": _next,
        "take_task_fn": _take,
        "release_task_fn": _release,
        "launch_task_fn": _launch,
        "done_checker_fn": _done,
        "sleep_fn": _sleep,
        "print_fn": _print,
        "log_op_fn": _log,
        "messages": messages,
        "log_entries": log_entries,
        "sleep_counter": sleep_counter,
        "poll_counter": poll_counter,
        "proc": proc,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExitOnEmpty:
    """exit_on_empty=True → exit immediately when queue is empty."""

    def test_empty_queue_exits_zero(self, tmp_path):
        h = _make_helpers(task_sequence=[])
        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="test-agent",
            exit_on_empty=True,
            interval=1,
            **{k: v for k, v in h.items() if k not in ("messages", "log_entries", "sleep_counter", "poll_counter", "proc")},
        )
        assert rc == 0
        assert any("Queue empty" in m or "exit_on_empty" in m or "exiting" in m.lower() for m in h["messages"])

    def test_empty_queue_no_sleep_when_exit_on_empty(self, tmp_path):
        """With exit_on_empty, we should not sleep before exiting."""
        h = _make_helpers(task_sequence=[], sleep_limit=0)
        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="test-agent",
            exit_on_empty=True,
            interval=1,
            **{k: v for k, v in h.items() if k not in ("messages", "log_entries", "sleep_counter", "poll_counter", "proc")},
        )
        assert rc == 0
        assert h["sleep_counter"]["n"] == 0

    def test_without_exit_on_empty_sleeps_then_exits_idle_limit(self, tmp_path):
        """Without exit_on_empty, poll sleeps; idle_limit stops the loop."""
        h = _make_helpers(task_sequence=[], sleep_limit=5)
        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="test-agent",
            exit_on_empty=False,
            idle_limit=3,
            interval=1,
            **{k: v for k, v in h.items() if k not in ("messages", "log_entries", "sleep_counter", "poll_counter", "proc")},
        )
        assert rc == 0
        assert h["sleep_counter"]["n"] == 2  # exit happens on 3rd idle before sleep


class TestTakeAndLaunch:
    """Verify task is taken, launched, and loop continues after done."""

    def test_single_task_taken_and_launched(self, tmp_path):
        task_id = "t-test-001"
        # Sequence: one task, then empty queue (exit_on_empty=True)
        h = _make_helpers(
            task_sequence=[task_id, None],
            take_results=[True],
            done_after_n_polls=1,
        )
        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="test-agent",
            exit_on_empty=True,
            interval=1,
            **{k: v for k, v in h.items() if k not in ("messages", "log_entries", "sleep_counter", "poll_counter", "proc")},
        )
        assert rc == 0
        # Verify log entries contain took + done
        ops = [e[0] for e in h["log_entries"]]
        assert "watch-took" in ops
        # Either watch-done or watch-proc-exit should be present
        assert "watch-done" in ops or "watch-proc-exit" in ops

    def test_multiple_tasks_processed_in_sequence(self, tmp_path):
        t1, t2 = "t-seq-001", "t-seq-002"
        h = _make_helpers(
            task_sequence=[t1, t2, None],
            take_results=[True, True],
            done_after_n_polls=1,
        )
        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="test-agent",
            exit_on_empty=True,
            interval=1,
            **{k: v for k, v in h.items() if k not in ("messages", "log_entries", "sleep_counter", "poll_counter", "proc")},
        )
        assert rc == 0
        took_entries = [e for e in h["log_entries"] if e[0] == "watch-took"]
        assert len(took_entries) == 2
        assert took_entries[0][1] == t1
        assert took_entries[1][1] == t2

    def test_launch_called_once_per_task(self, tmp_path):
        launch_calls = []
        original_launch_seq = ["t-call-001", None]
        task_iter = iter(original_launch_seq)

        def _next(role):
            try:
                return next(task_iter)
            except StopIteration:
                return None

        def _launch(tid):
            launch_calls.append(tid)
            return _MockProc()

        def _done(tid):
            return True  # immediately done

        def _take(tid, aid):
            return True

        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="test-agent",
            exit_on_empty=True,
            interval=1,
            next_task_fn=_next,
            take_task_fn=_take,
            release_task_fn=lambda t, a: None,
            launch_task_fn=_launch,
            done_checker_fn=_done,
            log_op_fn=lambda *a: None,
            print_fn=lambda m: None,
            sleep_fn=lambda s: None,
        )
        assert rc == 0
        assert launch_calls == ["t-call-001"]


class TestLockProtocol:
    """Verify lock contention is handled gracefully."""

    def test_locked_task_retried_after_sleep(self, tmp_path):
        """If take fails (lock held), we sleep and retry; second attempt succeeds."""
        task_id = "t-locked"
        call_count = {"next": 0, "take": 0}

        def _next(role):
            call_count["next"] += 1
            if call_count["next"] <= 2:
                return task_id  # available on both tries
            return None  # empty after second attempt

        def _take(tid, aid):
            call_count["take"] += 1
            if call_count["take"] == 1:
                return False  # first attempt: locked
            return True  # second attempt: success

        done_state = {"done": False}

        def _done(tid):
            done_state["done"] = True
            return True

        sleep_calls = []

        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="test-agent",
            exit_on_empty=True,
            interval=1,
            next_task_fn=_next,
            take_task_fn=_take,
            release_task_fn=lambda t, a: None,
            launch_task_fn=lambda t: _MockProc(),
            done_checker_fn=_done,
            log_op_fn=lambda *a: None,
            print_fn=lambda m: None,
            sleep_fn=lambda s: sleep_calls.append(s),
        )
        assert rc == 0
        assert call_count["take"] == 2
        # Should have slept once for the locked retry
        assert len(sleep_calls) >= 1


class TestIntervalRespect:
    """Verify the poll interval is used for both task-done polling and idle waits."""

    def test_polling_interval_used_while_waiting(self, tmp_path):
        """When done returns False initially, sleep is called with correct interval."""
        task_id = "t-poll"
        poll_count = {"n": 0}
        sleep_calls = []

        def _next(role):
            return task_id if poll_count["n"] == 0 else None

        def _done(tid):
            poll_count["n"] += 1
            return poll_count["n"] >= 3  # done on third poll

        def _sleep(s):
            sleep_calls.append(s)
            # After 3 sleeps we don't want infinite loop
            if len(sleep_calls) > 10:
                raise RuntimeError("too many sleeps")

        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="test-agent",
            exit_on_empty=True,
            interval=42,
            next_task_fn=_next,
            take_task_fn=lambda t, a: True,
            release_task_fn=lambda t, a: None,
            launch_task_fn=lambda t: _MockProc(),
            done_checker_fn=_done,
            log_op_fn=lambda *a: None,
            print_fn=lambda m: None,
            sleep_fn=_sleep,
        )
        assert rc == 0
        # All sleeps should use the configured interval (42)
        assert all(s == 42 for s in sleep_calls)

    def test_idle_sleep_uses_interval(self, tmp_path):
        """When queue is empty and exit_on_empty=False, sleep uses interval."""
        sleep_calls = []

        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="test-agent",
            exit_on_empty=False,
            idle_limit=2,
            interval=99,
            next_task_fn=lambda r: None,
            take_task_fn=lambda t, a: True,
            release_task_fn=lambda t, a: None,
            launch_task_fn=lambda t: _MockProc(),
            done_checker_fn=lambda t: True,
            log_op_fn=lambda *a: None,
            print_fn=lambda m: None,
            sleep_fn=lambda s: sleep_calls.append(s),
        )
        assert rc == 0
        assert all(s == 99 for s in sleep_calls)


class TestGracefulExit:
    """Verify KeyboardInterrupt causes clean exit with lock release."""

    def test_ctrl_c_releases_lock(self, tmp_path):
        released = []
        in_launch = {"v": False}

        def _next(role):
            return "t-ctrl-c" if not in_launch["v"] else None

        def _launch(tid):
            in_launch["v"] = True
            raise KeyboardInterrupt

        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="test-agent",
            exit_on_empty=True,
            interval=1,
            next_task_fn=_next,
            take_task_fn=lambda t, a: True,
            release_task_fn=lambda t, a: released.append(t),
            launch_task_fn=_launch,
            done_checker_fn=lambda t: False,
            log_op_fn=lambda *a: None,
            print_fn=lambda m: None,
            sleep_fn=lambda s: None,
        )
        assert rc == 0
        # Lock should be released on interrupt
        assert "t-ctrl-c" in released

    def test_ctrl_c_on_idle_exits_cleanly(self, tmp_path):
        """Ctrl-C while waiting for next task (no current task) exits with 0."""
        call_count = {"n": 0}

        def _sleep(s):
            call_count["n"] += 1
            if call_count["n"] >= 1:
                raise KeyboardInterrupt

        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="test-agent",
            exit_on_empty=False,
            interval=1,
            next_task_fn=lambda r: None,
            take_task_fn=lambda t, a: True,
            release_task_fn=lambda t, a: None,
            launch_task_fn=lambda t: _MockProc(),
            done_checker_fn=lambda t: True,
            log_op_fn=lambda *a: None,
            print_fn=lambda m: None,
            sleep_fn=_sleep,
        )
        assert rc == 0


class TestRoleFilter:
    """Verify role filter is passed to next_task_fn."""

    def test_role_passed_to_next(self, tmp_path):
        roles_seen = []

        def _next(role):
            roles_seen.append(role)
            return None

        run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="test-agent",
            role="developer",
            exit_on_empty=True,
            interval=1,
            next_task_fn=_next,
            take_task_fn=lambda t, a: True,
            release_task_fn=lambda t, a: None,
            launch_task_fn=lambda t: _MockProc(),
            done_checker_fn=lambda t: True,
            log_op_fn=lambda *a: None,
            print_fn=lambda m: None,
            sleep_fn=lambda s: None,
        )
        assert roles_seen[0] == "developer"

    def test_no_role_passes_none(self, tmp_path):
        roles_seen = []

        def _next(role):
            roles_seen.append(role)
            return None

        run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="test-agent",
            role=None,
            exit_on_empty=True,
            interval=1,
            next_task_fn=_next,
            take_task_fn=lambda t, a: True,
            release_task_fn=lambda t, a: None,
            launch_task_fn=lambda t: _MockProc(),
            done_checker_fn=lambda t: True,
            log_op_fn=lambda *a: None,
            print_fn=lambda m: None,
            sleep_fn=lambda s: None,
        )
        assert roles_seen[0] is None
