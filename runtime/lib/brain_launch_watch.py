"""brain_launch_watch — watch-loop logic for brain-launch --watch (no task-id).

This module provides the testable core of the ``brain-launch --watch`` standalone
mode.  The shell wrapper in ``bin/brain-launch`` calls :func:`run_watch_loop` after
argument parsing; tests exercise this function directly by patching the subprocess
helpers.

Algorithm
---------
1. ``next_task_fn(role)`` — call ``brain-task next [--role R]`` → return id or ``None``.
2. ``take_task_fn(id, agent)`` — call ``brain-task take <id> --as <agent>`` → True on success.
3. Launch the task via ``brain-launch <id>`` in a subprocess (foreground/blocking).
4. Poll ``done_checker_fn(id)`` every ``interval`` seconds until it returns True.
5. Release lock (best-effort), loop back to step 1.
6. Exit when queue is empty AND ``exit_on_empty`` is True, or on KeyboardInterrupt.
"""

from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Default subprocess helpers — call real brain-* commands
# ---------------------------------------------------------------------------

def _default_next_task(role: Optional[str], env=None) -> Optional[str]:
    """Call 'brain-task next [--role R] --json' and return task-id or None."""
    cmd = ["brain-task", "next", "--json"]
    if role:
        cmd += ["--role", role]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout.strip())
        if data.get("ok") and data.get("task", {}).get("id"):
            return data["task"]["id"]
        return None
    except Exception:
        return None


def _default_take_task(task_id: str, agent_id: str, env=None) -> bool:
    """Call 'brain-task take <id> --as <agent>' and return True on success."""
    cmd = ["brain-task", "take", task_id, "--as", agent_id]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        return result.returncode == 0
    except Exception:
        return False


def _default_release_task(task_id: str, agent_id: str, env=None) -> None:
    """Call 'brain-lock release <id> --as <agent>' (best-effort)."""
    cmd = ["brain-lock", "release", task_id, "--as", agent_id]
    try:
        subprocess.run(cmd, capture_output=True, text=True, env=env)
    except Exception:
        pass


def _default_launch_task(task_id: str, env=None):
    """Call 'brain-launch <id>' (foreground blocking via wait)."""
    cmd = ["brain-launch", task_id]
    proc = subprocess.Popen(cmd, env=env)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
    return proc


def _default_done_checker(task_id: str, done_path: str, active_path: str) -> bool:
    """Return True if task_id appears in done.md OR is marked [x] in active.md."""
    try:
        done_text = Path(done_path).read_text()
        if task_id in done_text:
            return True
        active_text = Path(active_path).read_text()
        if re.search(rf"- \[x\].*{re.escape(task_id)}", active_text):
            return True
        return False
    except Exception:
        return False


def _default_log_op(op: str, task_id: str, agent_id: str, extra: str, log_path: str) -> None:
    """Append a log line to wiki/log.md."""
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"## [{ts}] {op} | {task_id} | {agent_id} | {extra}\n"
    try:
        with open(log_path, "a") as f:
            f.write(line)
    except Exception:
        pass


def _default_fed_sync(env=None) -> None:
    """Call 'brain-federation sync' (best-effort)."""
    cmd = ["brain-federation", "sync"]
    try:
        subprocess.run(cmd, capture_output=True, text=True, env=env)
    except Exception:
        pass


def _default_ops_refresh(env=None) -> None:
    """Call 'brain-ops refresh' (best-effort)."""
    cmd = ["brain-ops", "refresh"]
    try:
        subprocess.run(cmd, capture_output=True, text=True, env=env)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Core watch loop
# ---------------------------------------------------------------------------

def run_watch_loop(
    *,
    brain_path: str,
    agent_id: str,
    role: Optional[str] = None,
    interval: int = 30,
    sync_interval: int = 300,
    ops_interval: int = 600,
    exit_on_empty: bool = False,
    idle_limit: int = 0,
    # Injectable helpers for unit testing
    next_task_fn: Optional[Callable] = None,
    take_task_fn: Optional[Callable] = None,
    release_task_fn: Optional[Callable] = None,
    launch_task_fn: Optional[Callable] = None,
    done_checker_fn: Optional[Callable] = None,
    fed_sync_fn: Optional[Callable] = None,
    ops_refresh_fn: Optional[Callable] = None,
    log_op_fn: Optional[Callable] = None,
    print_fn: Optional[Callable] = None,
    sleep_fn: Optional[Callable] = None,
) -> int:
    """
    Run the watch loop.

    Parameters
    ----------
    brain_path:
        Path to brain home (e.g. ``~/brain``).
    agent_id:
        Agent identifier string (used with lock protocol).
    role:
        Optional role filter passed to ``brain-task next``.
    interval:
        Polling interval in seconds while waiting for a task to complete.
    sync_interval:
        Interval in seconds for periodic ``brain-federation sync``.
    ops_interval:
        Interval in seconds for periodic ``brain-ops refresh``.
    exit_on_empty:
        If True, exit with code 0 when no next task is available.
        If False, sleep ``interval`` seconds and retry indefinitely.
    idle_limit:
        Maximum number of consecutive idle (empty queue) rounds before
        exiting, regardless of ``exit_on_empty``.  0 = unlimited.
    Returns
    -------
    int
        0 on clean exit (empty queue + exit_on_empty, idle_limit, Ctrl-C).
        1 on unexpected error.

    next_task_fn, take_task_fn, fed_sync_fn, ops_refresh_fn, ...:
        Injectable callables for unit testing.  When None, the default
        helpers that call real brain-* commands are used.
    """
    done_path = str(Path(brain_path) / "tasks" / "done.md")
    active_path = str(Path(brain_path) / "tasks" / "active.md")
    log_path = str(Path(brain_path) / "wiki" / "log.md")

    _next = next_task_fn if next_task_fn is not None else (lambda r: _default_next_task(r))
    _take = take_task_fn if take_task_fn is not None else (lambda tid, aid: _default_take_task(tid, aid))
    _release = release_task_fn if release_task_fn is not None else (lambda tid, aid: _default_release_task(tid, aid))
    _launch = launch_task_fn if launch_task_fn is not None else (lambda tid: _default_launch_task(tid))
    _done = done_checker_fn if done_checker_fn is not None else (lambda tid: _default_done_checker(tid, done_path, active_path))
    _fed_sync = fed_sync_fn if fed_sync_fn is not None else (lambda: _default_fed_sync())
    _ops_refresh = ops_refresh_fn if ops_refresh_fn is not None else (lambda: _default_ops_refresh())
    _log = log_op_fn if log_op_fn is not None else (lambda op, tid, aid, extra: _default_log_op(op, tid, aid, extra, log_path))
    _print = print_fn if print_fn is not None else print
    _sleep = sleep_fn if sleep_fn is not None else time.sleep

    _print(f"[watch] Starting watch loop (agent: {agent_id})")
    if role:
        _print(f"[watch] Role filter: {role}")
    _print(f"[watch] Poll interval: {interval}s | sync: {sync_interval}s | ops: {ops_interval}s")
    if exit_on_empty:
        _print(f"[watch] exit_on_empty: {exit_on_empty}")
    if idle_limit:
        _print(f"[watch] Idle limit: {idle_limit} rounds")
    _print("[watch] Press Ctrl-C to stop.")

    idle_rounds = 0
    current_task: Optional[str] = None
    last_sync_ts = 0.0
    last_ops_ts = 0.0

    try:
        while True:
            # --- Periodic Federation Sync ---
            now = time.time()
            if sync_interval > 0 and (now - last_sync_ts >= sync_interval):
                _print("[watch] Triggering federation sync...")
                _fed_sync()
                last_sync_ts = now

            # --- Periodic Ops Refresh (Dashboard Data) ---
            if ops_interval > 0 and (now - last_ops_ts >= ops_interval):
                _print("[watch] Triggering ops data refresh...")
                _ops_refresh()
                last_ops_ts = now

            # --- Find next available task ---
            next_id = _next(role)

            if next_id is None:
                idle_rounds += 1
                _print(f"[watch] No available tasks (idle round {idle_rounds}).")
                _log("watch-idle", "", agent_id, f"round={idle_rounds}")

                if exit_on_empty:
                    _print("[watch] Queue empty — exiting (--exit-on-empty).")
                    return 0

                if idle_limit and idle_rounds >= idle_limit:
                    _print(f"[watch] Idle limit {idle_limit} reached — exiting.")
                    return 0

                _sleep(interval)
                continue

            idle_rounds = 0  # reset on finding a task

            # --- Try to take the task (lock protocol) ---
            _print(f"[watch] Found task: {next_id} — acquiring lock...")
            if not _take(next_id, agent_id):
                _print(f"[watch] Could not take {next_id} (locked by another agent). Retrying in {interval}s.")
                _sleep(interval)
                continue

            current_task = next_id
            _log("watch-took", next_id, agent_id, "")
            _print(f"[watch] Took {next_id}. Launching...")

            # --- Launch the task ---
            proc = _launch(next_id)
            pid_str = str(getattr(proc, "pid", "?"))
            _log("watch-launched", next_id, agent_id, f"pid={pid_str}")

            # --- Poll until done ---
            _print(f"[watch] Waiting for {next_id} to complete (poll every {interval}s)...")
            while True:
                if _done(next_id):
                    _print(f"[watch] Task {next_id} completed.")
                    _log("watch-done", next_id, agent_id, "")
                    break
                # Check if subprocess finished (when launch_task_fn returns early)
                if hasattr(proc, "poll") and proc.poll() is not None:
                    _print(f"[watch] Subprocess for {next_id} exited (rc={proc.returncode}).")
                    _log("watch-proc-exit", next_id, agent_id, f"rc={proc.returncode}")
                    break
                _sleep(interval)

            # --- Release lock (best-effort) ---
            _release(next_id, agent_id)
            current_task = None

    except KeyboardInterrupt:
        _print("\n[watch] Interrupted by user.")
        if current_task:
            _print(f"[watch] Releasing lock on {current_task}...")
            _release(current_task, agent_id)
            _log("watch-interrupt", current_task, agent_id, "ctrl-c")
        return 0
    except Exception as exc:  # noqa: BLE001
        _print(f"[watch] Unexpected error: {exc}")
        if current_task:
            _release(current_task, agent_id)
        return 1


# ---------------------------------------------------------------------------
# CLI entry point (called from brain-launch --watch when no task-id)
# ---------------------------------------------------------------------------

def main(argv=None):
    """
    CLI entry:
        python3 -m brain_launch_watch <brain_path> <agent_id>
            [--role R] [--interval N] [--exit-on-empty] [--idle-limit N]
    """
    import argparse
    parser = argparse.ArgumentParser(prog="brain_launch_watch")
    parser.add_argument("brain_path", help="BRAIN home directory")
    parser.add_argument("agent_id", help="Agent identifier (for lock protocol)")
    parser.add_argument("--role", default=None)
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--sync-interval", type=int, default=300)
    parser.add_argument("--ops-interval", type=int, default=600)
    parser.add_argument("--exit-on-empty", action="store_true")
    parser.add_argument("--idle-limit", type=int, default=0)
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    rc = run_watch_loop(
        brain_path=args.brain_path,
        agent_id=args.agent_id,
        role=args.role,
        interval=args.interval,
        sync_interval=args.sync_interval,
        ops_interval=args.ops_interval,
        exit_on_empty=args.exit_on_empty,
        idle_limit=args.idle_limit,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
