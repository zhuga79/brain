"""brain_launch_watch — watch-loop logic for brain-launch --watch (no task-id).

This module provides the testable core of the ``brain-launch --watch`` standalone
mode.  The shell wrapper in ``bin/brain-launch`` calls :func:`run_watch_loop` after
argument parsing; tests exercise this function directly by patching the subprocess
helpers.

Algorithm
---------
1. ``next_task_fn(role)`` — call ``brain-task next [--role R] --headless-only``
   → return id or ``None``.  Interactive tasks never enter this loop: their
   outcome depends on a human, see docs/decisions/decision-interactive-surface.md.
2. Refuse to take anything while ``wip_limit`` tasks are already in progress
   under this agent id.
3. ``take_task_fn(id, agent)`` — call ``brain-task take <id> --as <agent>``,
   which acquires the lock under the same agent id → True on success.
4. Launch the task via ``brain-launch <id>`` in a subprocess (foreground/blocking).
5. Poll ``done_checker_fn(id)`` every ``interval`` seconds until it returns True.
6. Release the task (``brain-task release`` returns it to ``[ ]`` and drops the
   lock), loop back to step 1.
7. Exit when queue is empty AND ``exit_on_empty`` is True, when ``max_failures``
   consecutive launches fail, when ``max_tasks`` is reached, or on KeyboardInterrupt.

Safety stop (t-2026-08-14-launch-watch-loop-safety-stop)
--------------------------------------------------------
``--dry-run`` prints the plan and returns without a single write: no queue
mutation, no lock, no council directory, no tmux, no git commit.  Before the
fix ``--dry-run`` was dropped by the shell wrapper for the standalone watch
mode, and a "plan only" invocation marked eleven tasks in progress in two
minutes because every failed launch immediately grabbed the next task and the
previous one was never returned to ``[ ]``.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Default subprocess helpers — call real brain-* commands
# ---------------------------------------------------------------------------

def _default_next_task(role: Optional[str], env=None, surface: str = "headless") -> Optional[str]:
    """Call 'brain-task next [--role R] --headless-only --json' → task-id or None.

    The surface filter is applied by the query, not by the caller afterwards:
    a filter applied after the fact is a filter somebody eventually forgets.
    """
    cmd = ["brain-task", "next", "--json"]
    if surface:
        cmd += ["--surface", surface]
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
    """Return the task to the queue and drop its lock (best-effort).

    ``brain-task release`` does both — ``[~]`` → ``[ ]`` and lock release.  The
    old implementation released only the lock, so every task the loop touched
    stayed ``[~]`` forever; eleven of them piled up during the 2026-08-14
    incident.  If the task is no longer in progress (it completed), the queue
    command refuses and only the lock needs clearing.
    """
    try:
        result = subprocess.run(
            ["brain-task", "release", task_id, "--as", agent_id],
            capture_output=True, text=True, env=env,
        )
        if result.returncode == 0:
            return
    except Exception:
        pass
    try:
        subprocess.run(
            ["brain-lock", "release", task_id, "--as", agent_id],
            capture_output=True, text=True, env=env,
        )
    except Exception:
        pass


def _default_in_progress_count(agent_id: str, active_path: str) -> int:
    """How many tasks are currently ``[~]`` under this agent id."""
    try:
        text = Path(active_path).read_text()
    except Exception:
        return 0
    count = 0
    current_is_in_progress = False
    for line in text.splitlines():
        if line.startswith("- ["):
            current_is_in_progress = line.startswith("- [~]")
            continue
        if current_is_in_progress and line.strip().startswith("by:"):
            if line.split(":", 1)[1].strip() == agent_id:
                count += 1
    return count


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
# Dry-run plan
# ---------------------------------------------------------------------------

def _print_watch_plan(
    *, print_fn, next_fn, in_progress_fn, agent_id, role, surface, interval,
    sync_interval, ops_interval, wip_limit, max_failures, max_tasks,
    exit_on_empty, idle_limit,
) -> int:
    """Print what the loop would do. Reads the queue; writes nothing.

    Only ``brain-task next`` runs here, and it is a read.  Nothing else on this
    path may touch active.md, council/, the lock directory, git or tmux.
    """
    print_fn("Watch-loop plan (standalone --watch)")
    print_fn(f"  Agent id     : {agent_id}")
    print_fn(f"  Role filter  : {role or '<any>'}")
    print_fn(f"  Surface      : {surface or '<any>'} — interactive tasks stay out of headless auto-next")
    print_fn(f"  Intervals    : poll {interval}s | sync {sync_interval}s | ops {ops_interval}s")
    print_fn(f"  WIP limit    : {wip_limit} task(s) in progress at a time")
    print_fn(f"  Failure stop : {max_failures} consecutive failed launches")
    print_fn(f"  Task limit   : {max_tasks or '<unlimited>'}")
    print_fn(f"  On empty     : {'exit' if exit_on_empty else 'wait'}"
             + (f" | idle limit {idle_limit}" if idle_limit else ""))
    try:
        in_flight = in_progress_fn(agent_id)
    except Exception:  # noqa: BLE001
        in_flight = 0
    print_fn(f"  In progress  : {in_flight} task(s) already held by this agent")
    try:
        next_id = next_fn(role)
    except Exception:  # noqa: BLE001
        next_id = None
    print_fn(f"  Next task    : {next_id or '<none available>'}")
    if not next_id:
        print_fn("  Would run    : nothing — no available headless task in the queue")
    elif in_flight >= wip_limit:
        print_fn(f"  Would run    : nothing — WIP limit {wip_limit} already reached")
    else:
        print_fn(f"  Would run    : brain-task take {next_id} --as {agent_id}")
        print_fn(f"                 brain-launch {next_id}")
    print_fn("  [DRY-RUN: no side effects — no queue write, no lock, no council, no tmux, no git]")
    return 0


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
    dry_run: bool = False,
    surface: str = "headless",
    wip_limit: int = 1,
    max_failures: int = 3,
    max_tasks: int = 0,
    # Injectable helpers for unit testing
    next_task_fn: Optional[Callable] = None,
    take_task_fn: Optional[Callable] = None,
    release_task_fn: Optional[Callable] = None,
    launch_task_fn: Optional[Callable] = None,
    done_checker_fn: Optional[Callable] = None,
    in_progress_count_fn: Optional[Callable] = None,
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
    dry_run:
        Print the plan and return 0 without a single write — no take, no
        launch, no lock, no log line, no federation sync, no ops refresh.
    surface:
        Launch surface passed to ``brain-task next``.  ``headless`` (default)
        keeps human-in-the-loop tasks out of the loop entirely.
    wip_limit:
        Maximum number of tasks this agent may hold in progress at once.
        The loop is sequential, so this is a safety stop rather than a
        scheduler: it refuses to take task N+1 while N is still ``[~]``.
    max_failures:
        Consecutive failed launches after which the loop stops.  Without it a
        launch that fails instantly walks the whole queue in seconds.
    max_tasks:
        Hard cap on tasks processed in one run.  0 = unlimited.

    Returns
    -------
    int
        0 on clean exit (empty queue + exit_on_empty, idle_limit, max_tasks,
        Ctrl-C, dry-run).  1 on unexpected error or on the failure limit.

    next_task_fn, take_task_fn, fed_sync_fn, ops_refresh_fn, ...:
        Injectable callables for unit testing.  When None, the default
        helpers that call real brain-* commands are used.
    """
    done_path = str(Path(brain_path) / "tasks" / "done.md")
    active_path = str(Path(brain_path) / "tasks" / "active.md")
    log_path = str(Path(brain_path) / "wiki" / "log.md")

    # Каждая brain-* команда цикла работает по тому же дереву, что назвали нам.
    # Без этого подчинённые команды резолвили BRAIN_PATH сами и уходили в
    # боевое дерево, хотя цикл запускали по временному — то есть тест мог
    # тронуть живую очередь.
    env = {**os.environ, "BRAIN_PATH": str(brain_path)}

    _next = next_task_fn if next_task_fn is not None else (lambda r: _default_next_task(r, env, surface=surface))
    _take = take_task_fn if take_task_fn is not None else (lambda tid, aid: _default_take_task(tid, aid, env))
    _release = release_task_fn if release_task_fn is not None else (lambda tid, aid: _default_release_task(tid, aid, env))
    _launch = launch_task_fn if launch_task_fn is not None else (lambda tid: _default_launch_task(tid, env))
    _done = done_checker_fn if done_checker_fn is not None else (lambda tid: _default_done_checker(tid, done_path, active_path))
    _in_progress = (
        in_progress_count_fn if in_progress_count_fn is not None
        else (lambda aid: _default_in_progress_count(aid, active_path))
    )
    _fed_sync = fed_sync_fn if fed_sync_fn is not None else (lambda: _default_fed_sync(env))
    _ops_refresh = ops_refresh_fn if ops_refresh_fn is not None else (lambda: _default_ops_refresh(env))
    _log = log_op_fn if log_op_fn is not None else (lambda op, tid, aid, extra: _default_log_op(op, tid, aid, extra, log_path))
    _print = print_fn if print_fn is not None else print
    _sleep = sleep_fn if sleep_fn is not None else time.sleep

    wip_limit = max(1, int(wip_limit))

    if dry_run:
        return _print_watch_plan(
            print_fn=_print, next_fn=_next, in_progress_fn=_in_progress, agent_id=agent_id,
            role=role, surface=surface, interval=interval, sync_interval=sync_interval,
            ops_interval=ops_interval, wip_limit=wip_limit, max_failures=max_failures,
            max_tasks=max_tasks, exit_on_empty=exit_on_empty, idle_limit=idle_limit,
        )

    _print(f"[watch] Starting watch loop (agent: {agent_id})")
    if role:
        _print(f"[watch] Role filter: {role}")
    _print(f"[watch] Surface filter: {surface or 'any'}")
    _print(f"[watch] Poll interval: {interval}s | sync: {sync_interval}s | ops: {ops_interval}s")
    _print(f"[watch] WIP limit: {wip_limit} | max consecutive failures: {max_failures}"
           + (f" | max tasks: {max_tasks}" if max_tasks else ""))
    if exit_on_empty:
        _print(f"[watch] exit_on_empty: {exit_on_empty}")
    if idle_limit:
        _print(f"[watch] Idle limit: {idle_limit} rounds")
    _print("[watch] Press Ctrl-C to stop.")

    idle_rounds = 0
    failures = 0
    processed = 0
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

            # --- WIP guard: never grab the queue wholesale ---
            in_flight = _in_progress(agent_id)
            if in_flight >= wip_limit:
                _print(f"[watch] WIP limit reached ({in_flight}/{wip_limit} in progress) — waiting.")
                _log("watch-wip-limit", "", agent_id, f"in_flight={in_flight} limit={wip_limit}")
                if exit_on_empty:
                    _print("[watch] Not taking more work — exiting (--exit-on-empty).")
                    return 0
                _sleep(interval)
                continue

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
            completed = False
            exit_code = 0
            while True:
                if _done(next_id):
                    _print(f"[watch] Task {next_id} completed.")
                    _log("watch-done", next_id, agent_id, "")
                    completed = True
                    break
                # Check if subprocess finished (when launch_task_fn returns early)
                if hasattr(proc, "poll") and proc.poll() is not None:
                    exit_code = getattr(proc, "returncode", 0) or 0
                    _print(f"[watch] Subprocess for {next_id} exited (rc={exit_code}).")
                    _log("watch-proc-exit", next_id, agent_id, f"rc={exit_code}")
                    break
                _sleep(interval)

            # --- Hand the task back: [~] → [ ] plus lock release ---
            _release(next_id, agent_id)
            current_task = None
            processed += 1

            if completed or exit_code == 0:
                failures = 0
            else:
                failures += 1
                _print(f"[watch] Launch of {next_id} failed ({failures}/{max_failures} consecutive).")
                _log("watch-launch-failed", next_id, agent_id, f"rc={exit_code} streak={failures}")
                if max_failures and failures >= max_failures:
                    _print(f"[watch] {failures} consecutive launch failures — stopping. "
                           "Queue left untouched; fix the launch first.")
                    _log("watch-stop", next_id, agent_id, f"consecutive_failures={failures}")
                    return 1
                # Never spin: a launch that fails instantly must not walk the queue.
                _sleep(interval)

            if max_tasks and processed >= max_tasks:
                _print(f"[watch] Task limit {max_tasks} reached — exiting.")
                return 0

    except KeyboardInterrupt:
        _print("\n[watch] Interrupted by user.")
        if current_task:
            _print(f"[watch] Releasing {current_task}...")
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
            [--role R] [--surface S] [--interval N] [--exit-on-empty]
            [--idle-limit N] [--wip N] [--max-failures N] [--max-tasks N]
            [--dry-run]
    """
    import argparse
    parser = argparse.ArgumentParser(prog="brain_launch_watch")
    parser.add_argument("brain_path", help="BRAIN home directory")
    parser.add_argument("agent_id", help="Agent identifier (for lock protocol)")
    parser.add_argument("--role", default=None)
    parser.add_argument(
        "--surface", default="headless", choices=["headless", "interactive", "any"],
        help="launch surface filter; headless keeps human-in-the-loop tasks out",
    )
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--sync-interval", type=int, default=300)
    parser.add_argument("--ops-interval", type=int, default=600)
    parser.add_argument("--exit-on-empty", action="store_true")
    parser.add_argument("--idle-limit", type=int, default=0)
    parser.add_argument("--wip", type=int, default=1, help="max tasks in progress at once")
    parser.add_argument("--max-failures", type=int, default=3, help="consecutive failed launches before stopping")
    parser.add_argument("--max-tasks", type=int, default=0, help="hard cap on tasks per run (0 = unlimited)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    rc = run_watch_loop(
        brain_path=args.brain_path,
        agent_id=args.agent_id,
        role=args.role,
        surface="" if args.surface == "any" else args.surface,
        interval=args.interval,
        sync_interval=args.sync_interval,
        ops_interval=args.ops_interval,
        exit_on_empty=args.exit_on_empty,
        idle_limit=args.idle_limit,
        wip_limit=args.wip,
        max_failures=args.max_failures,
        max_tasks=args.max_tasks,
        dry_run=args.dry_run,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
