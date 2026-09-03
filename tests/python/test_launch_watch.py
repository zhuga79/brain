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

import brain_launch_watch  # noqa: E402
from brain_launch_watch import run_watch_loop  # noqa: E402


# ---------------------------------------------------------------------------
# Hermetic guard
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_real_commands(monkeypatch):
    """No test in this file may shell out to a real brain-* command.

    Until t-2026-08-14 the loop's default federation-sync and ops-refresh
    helpers ran for real in every test that did not inject them, against the
    operator's live tree. A watch-loop test must never touch live data.
    """
    class _Blocked(types.SimpleNamespace):
        @staticmethod
        def run(cmd, **kwargs):
            raise AssertionError(f"test tried to run a real command: {cmd}")

        @staticmethod
        def Popen(cmd, **kwargs):  # noqa: N802 - mirrors subprocess API
            raise AssertionError(f"test tried to spawn a real process: {cmd}")

    monkeypatch.setattr(brain_launch_watch, "subprocess", _Blocked)


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


class TestDryRun:
    """t-2026-08-14: --dry-run must not write anything, in any combination.

    The live incident ran `brain-launch --watch --auto-next --dry-run` and got
    eleven tasks marked in progress. The flag has to reach the loop itself.
    """

    def _forbidden(self, name):
        def _boom(*args, **kwargs):
            raise AssertionError(f"dry-run called {name}")
        return _boom

    def test_dry_run_takes_nothing(self, tmp_path):
        messages = []
        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="dry-agent",
            dry_run=True,
            interval=1,
            next_task_fn=lambda r: "t-would-take",
            take_task_fn=self._forbidden("take"),
            release_task_fn=self._forbidden("release"),
            launch_task_fn=self._forbidden("launch"),
            done_checker_fn=self._forbidden("done"),
            in_progress_count_fn=lambda a: 0,
            fed_sync_fn=self._forbidden("fed_sync"),
            ops_refresh_fn=self._forbidden("ops_refresh"),
            log_op_fn=self._forbidden("log"),
            print_fn=messages.append,
            sleep_fn=self._forbidden("sleep"),
        )
        assert rc == 0
        text = "\n".join(messages)
        assert "DRY-RUN" in text
        assert "t-would-take" in text
        assert "brain-task take t-would-take --as dry-agent" in text

    def test_dry_run_never_writes_to_the_queue(self, tmp_path):
        """End-to-end on an isolated tree: files are byte-identical afterwards."""
        (tmp_path / "tasks").mkdir()
        (tmp_path / "wiki").mkdir()
        active = tmp_path / "tasks" / "active.md"
        done = tmp_path / "tasks" / "done.md"
        log = tmp_path / "wiki" / "log.md"
        active.write_text(
            "# Active\n\n- [ ] [P1] t-dry-one — First\n      role: developer   mode: solo\n"
        )
        done.write_text("# Done\n")
        log.write_text("# Log\n")
        before = {p: p.read_bytes() for p in (active, done, log)}

        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="dry-agent",
            dry_run=True,
            interval=1,
            next_task_fn=lambda r: "t-dry-one",
            print_fn=lambda m: None,
        )
        assert rc == 0
        for path, content in before.items():
            assert path.read_bytes() == content, path
        assert not (tmp_path / ".locks").exists()
        assert not (tmp_path / "council").exists()

    def test_dry_run_reports_nothing_to_do_when_wip_is_full(self, tmp_path):
        messages = []
        run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="dry-agent",
            dry_run=True,
            wip_limit=1,
            next_task_fn=lambda r: "t-blocked-by-wip",
            in_progress_count_fn=lambda a: 1,
            print_fn=messages.append,
        )
        text = "\n".join(messages)
        assert "nothing" in text.lower()
        assert "brain-task take" not in text


class TestHeadlessOnly:
    """Interactive tasks must not enter headless auto-next by any path."""

    def test_default_next_query_filters_surface(self, monkeypatch):
        seen = {}

        class _Result:
            returncode = 0
            stdout = '{"ok": false, "reason": "no_tasks"}'

        def _fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            return _Result()

        monkeypatch.setattr(brain_launch_watch.subprocess, "run", _fake_run)
        brain_launch_watch._default_next_task("developer")
        assert "--surface" in seen["cmd"]
        assert seen["cmd"][seen["cmd"].index("--surface") + 1] == "headless"

    def test_surface_is_used_by_the_default_helper(self, tmp_path, monkeypatch):
        """The loop's default next helper carries the configured surface."""
        seen = []

        def _fake_default_next(role, env=None, surface="headless"):
            seen.append(surface)
            return None

        monkeypatch.setattr(brain_launch_watch, "_default_next_task", _fake_default_next)
        run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="surface-agent",
            exit_on_empty=True,
            interval=1,
            in_progress_count_fn=lambda a: 0,
            take_task_fn=lambda t, a: True,
            release_task_fn=lambda t, a: None,
            launch_task_fn=lambda t: _MockProc(),
            done_checker_fn=lambda t: True,
            fed_sync_fn=lambda: None,
            ops_refresh_fn=lambda: None,
            log_op_fn=lambda *a: None,
            print_fn=lambda m: None,
            sleep_fn=lambda s: None,
        )
        assert seen == ["headless"]


class TestWipAndFailureStop:
    """The loop must not walk the whole queue when launches fail."""

    def test_failed_launch_stops_after_max_failures(self, tmp_path):
        taken, released = [], []

        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="wip-agent",
            interval=1,
            max_failures=3,
            next_task_fn=lambda r: f"t-fail-{len(taken)}",
            take_task_fn=lambda t, a: (taken.append(t), True)[1],
            release_task_fn=lambda t, a: released.append(t),
            launch_task_fn=lambda t: _MockProc(returncode=1),
            done_checker_fn=lambda t: False,
            in_progress_count_fn=lambda a: 0,
            fed_sync_fn=lambda: None,
            ops_refresh_fn=lambda: None,
            log_op_fn=lambda *a: None,
            print_fn=lambda m: None,
            sleep_fn=lambda s: None,
        )
        assert rc == 1
        assert len(taken) == 3, taken
        # Every task the loop touched went back to the queue.
        assert released == taken

    def test_wip_limit_blocks_a_second_take(self, tmp_path):
        taken = []
        in_flight = {"n": 0}

        def _take(tid, aid):
            taken.append(tid)
            in_flight["n"] += 1
            return True

        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="wip-agent",
            exit_on_empty=True,
            interval=1,
            wip_limit=1,
            next_task_fn=lambda r: f"t-wip-{len(taken)}",
            take_task_fn=_take,
            release_task_fn=lambda t, a: None,   # deliberately does NOT clear [~]
            launch_task_fn=lambda t: _MockProc(),
            done_checker_fn=lambda t: True,
            in_progress_count_fn=lambda a: in_flight["n"],
            fed_sync_fn=lambda: None,
            ops_refresh_fn=lambda: None,
            log_op_fn=lambda *a: None,
            print_fn=lambda m: None,
            sleep_fn=lambda s: None,
        )
        assert rc == 0
        assert taken == ["t-wip-0"], taken

    def test_max_tasks_caps_one_run(self, tmp_path):
        taken = []
        rc = run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="cap-agent",
            interval=1,
            max_tasks=2,
            next_task_fn=lambda r: f"t-cap-{len(taken)}",
            take_task_fn=lambda t, a: (taken.append(t), True)[1],
            release_task_fn=lambda t, a: None,
            launch_task_fn=lambda t: _MockProc(),
            done_checker_fn=lambda t: True,
            in_progress_count_fn=lambda a: 0,
            fed_sync_fn=lambda: None,
            ops_refresh_fn=lambda: None,
            log_op_fn=lambda *a: None,
            print_fn=lambda m: None,
            sleep_fn=lambda s: None,
        )
        assert rc == 0
        assert taken == ["t-cap-0", "t-cap-1"]

    def test_in_progress_counter_reads_only_own_rows(self, tmp_path):
        active = tmp_path / "active.md"
        active.write_text(
            "# Active\n\n"
            "- [~] [P1] t-mine-1 — Mine\n      by: watch-agent\n"
            "- [~] [P1] t-theirs — Theirs\n      by: other-agent\n"
            "- [ ] [P1] t-open — Open\n      by: watch-agent\n"
        )
        assert brain_launch_watch._default_in_progress_count("watch-agent", str(active)) == 1


class TestReleaseReturnsTheTask:
    """Release must return [~] → [ ], not merely drop the lock."""

    def test_default_release_prefers_brain_task_release(self, monkeypatch):
        calls = []

        class _Result:
            returncode = 0

        def _fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _Result()

        monkeypatch.setattr(brain_launch_watch.subprocess, "run", _fake_run)
        brain_launch_watch._default_release_task("t-x", "agent-1")
        assert calls == [["brain-task", "release", "t-x", "--as", "agent-1"]]

    def test_default_release_falls_back_to_lock_release(self, monkeypatch):
        calls = []

        class _Result:
            def __init__(self, rc):
                self.returncode = rc

        def _fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _Result(1 if cmd[0] == "brain-task" else 0)

        monkeypatch.setattr(brain_launch_watch.subprocess, "run", _fake_run)
        brain_launch_watch._default_release_task("t-x", "agent-1")
        assert calls[-1] == ["brain-lock", "release", "t-x", "--as", "agent-1"]


class TestDefaultFedSyncTargetsTheWatchedTree:
    """t-2026-09-02-wiki-log-md: `brain-federation sync` resolves --repo from
    cwd, not $BRAIN_PATH, so the watch loop must name the tree explicitly.
    An unqualified call synced the system checkout during the smoke suite."""

    def test_default_fed_sync_passes_repo_and_brain(self, tmp_path, monkeypatch):
        calls = []

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        def _fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _Result()

        monkeypatch.setattr(brain_launch_watch.subprocess, "run", _fake_run)
        brain_launch_watch._default_fed_sync(str(tmp_path), env={})
        assert calls == [[
            "brain-federation", "sync",
            "--repo", str(tmp_path), "--brain", str(tmp_path),
        ]]

    def test_watch_loop_sync_names_the_brain_path(self, tmp_path, monkeypatch):
        (tmp_path / "tasks").mkdir()
        (tmp_path / "wiki").mkdir()
        (tmp_path / "tasks" / "active.md").write_text("# Active\n")
        (tmp_path / "tasks" / "done.md").write_text("# Done\n")
        (tmp_path / "wiki" / "log.md").write_text("# Log\n")
        calls = []

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(
            brain_launch_watch.subprocess, "run",
            lambda cmd, **kw: (calls.append(cmd), _Result())[1],
        )
        run_watch_loop(
            brain_path=str(tmp_path),
            agent_id="watch-agent",
            interval=1,
            sync_interval=1,
            ops_interval=0,
            exit_on_empty=True,
            next_task_fn=lambda r: None,
            take_task_fn=lambda t, a: True,
            launch_task_fn=lambda t: 0,
            done_checker_fn=lambda t: True,
            in_progress_count_fn=lambda a: 0,
            ops_refresh_fn=lambda: None,
            log_op_fn=lambda *a: None,
            print_fn=lambda *a: None,
            sleep_fn=lambda s: None,
        )
        sync_calls = [c for c in calls if c[:2] == ["brain-federation", "sync"]]
        assert sync_calls, "watch loop never called federation sync"
        assert "--repo" in sync_calls[0]
        assert sync_calls[0][sync_calls[0].index("--repo") + 1] == str(tmp_path)


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
