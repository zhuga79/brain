"""t-2026-08-16-autosave-uncommitted-agent-wor — save uncommitted executor work.

An executor that dies before committing leaves uncommitted work in its
worktree. When its stale lock is evicted (``brain-lock cleanup``, the
stale-takeover on the next ``acquire``, or ``reconcile_locks --fix``) that
work is one ``git checkout`` away from silent loss — and with parallel
``/tmp`` worktrees the queue does not even know which tree the executor used.

Two moving parts:

* **record** — at lock time the executor's git worktree root is written next
  to the lock (``.locks/<task-id>/worktree``). A crash cannot erase it; a
  non-git cwd records nothing (nothing to autosave).
* **autosave** — when the lock is evicted, any change in that tree relative
  to ``HEAD`` (tracked, staged or untracked, ``.gitignore`` honoured) is
  snapshotted into a commit that is placed on **no branch** and touches
  **neither the working tree nor the index**, then pinned under a
  ``wip-recovery/<task-id>`` tag so it survives the worktree's removal and a
  ``/tmp`` wipe. The tag name is dropped into a breadcrumb
  (``.locks/<task-id>.autosaved``) that the queue flushes into the task's
  ``resume:`` field once it is no longer holding the queue lock.

Idempotent: a second eviction with identical tree content is a no-op; with
different content it adds ``wip-recovery/<task-id>-<n>`` and never overwrites
an existing snapshot. Every git call is time-boxed and never raises — a
missing or broken tree degrades to "nothing saved", not to a crash inside
lock cleanup.

The split (git here, ``resume:`` write deferred) is deliberate: the eviction
call sites hold ``queue_lock``, and ``taskfile.annotate_resume`` takes it too;
doing the annotation inline would deadlock on the non-reentrant file lock.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_GIT_TIMEOUT = 30
_TAG_PREFIX = "wip-recovery"
_MAX_TAG_VARIANTS = 50


def _disabled() -> bool:
    """Skip entirely under a test harness. Both suites drive lock ops for
    testing from a cwd that is the live system checkout, so record_worktree
    would point at it and eviction would tag it. The smoke runner sets
    BRAIN_TEST_SANDBOX; the pytest autouse fixture sets BRAIN_AUTOSAVE_DISABLE.
    test_autosave.py clears the latter in its own fixtures to exercise this
    module for real."""
    return bool(os.environ.get("BRAIN_TEST_SANDBOX") or os.environ.get("BRAIN_AUTOSAVE_DISABLE"))


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """git in *cwd*, time-boxed, never raising. Caller's GIT_* is dropped
    (a hook's GIT_INDEX_FILE/GIT_DIR would otherwise point elsewhere)."""
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if env:
        full_env.update(env)
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT,
            env=full_env, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(list(args), returncode=1, stdout="", stderr="")


# Both live as sibling *files* of the lock dir, never inside it: `rm -rf
# .locks/<tid>/` and every `for d in .locks/*/` loop (dirs only) leave them
# alone, so the lock dir stays exactly `{owner}` for code that inspects it.
def _worktree_file(locks_root: Path | str, tid: str) -> Path:
    return Path(locks_root) / f"{tid}.worktree"


def _breadcrumb(locks_root: Path | str, tid: str) -> Path:
    return Path(locks_root) / f"{tid}.autosaved"


def record_worktree(locks_root: Path | str, tid: str, cwd: Path | str | None = None) -> Path | None:
    """Record the executor's git worktree root next to its lock. Called at
    acquire. ``cwd`` defaults to the current directory. Non-git → nothing."""
    if _disabled():
        return None
    try:
        base = Path(cwd).resolve() if cwd is not None else Path.cwd()
    except (OSError, RuntimeError):
        return None
    if not base.is_dir():
        return None
    res = _git(base, "rev-parse", "--show-toplevel")
    top = res.stdout.strip()
    if res.returncode != 0 or not top:
        return None
    wt_file = _worktree_file(locks_root, tid)
    try:
        wt_file.parent.mkdir(parents=True, exist_ok=True)
        wt_file.write_text(top + "\n", encoding="utf-8")
        # a resume from a previous interruption is superseded by fresh work
        _breadcrumb(locks_root, tid).unlink(missing_ok=True)
    except OSError:
        return None
    return wt_file


def read_worktree(locks_root: Path | str, tid: str) -> Path | None:
    try:
        top = _worktree_file(locks_root, tid).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not top:
        return None
    p = Path(top)
    return p if p.is_dir() and (p / ".git").exists() else None


def _snapshot_commit(wt: Path, message: str) -> str | None:
    """Commit capturing tracked+staged+untracked state of *wt* relative to
    HEAD, without touching its working tree or index. ``None`` when the tree
    already matches HEAD or git is unusable here."""
    head = _git(wt, "rev-parse", "--verify", "HEAD")
    head_sha = head.stdout.strip()
    if head.returncode != 0 or not head_sha:
        return None
    fd, tmp_index = tempfile.mkstemp(prefix="brain-autosave-idx-")
    os.close(fd)
    try:
        os.unlink(tmp_index)  # git creates it itself
    except OSError:
        pass
    try:
        env = {"GIT_INDEX_FILE": tmp_index}
        if _git(wt, "read-tree", "HEAD", env=env).returncode != 0:
            return None
        _git(wt, "add", "-A", env=env)  # tracked + untracked; .gitignore honoured
        tree = _git(wt, "write-tree", env=env).stdout.strip()
        if not tree:
            return None
        if tree == _git(wt, "rev-parse", f"{head_sha}^{{tree}}").stdout.strip():
            return None
        ident = {
            "GIT_AUTHOR_NAME": "brain-autosave", "GIT_AUTHOR_EMAIL": "autosave@brain.local",
            "GIT_COMMITTER_NAME": "brain-autosave", "GIT_COMMITTER_EMAIL": "autosave@brain.local",
        }
        sha = _git(wt, "commit-tree", tree, "-p", head_sha, "-m", message, env=ident).stdout.strip()
        return sha or None
    finally:
        try:
            os.unlink(tmp_index)
        except OSError:
            pass


def _tree_of(wt: Path, ref: str) -> str:
    return _git(wt, "rev-parse", "--verify", "--quiet", f"{ref}^{{tree}}").stdout.strip()


def _pick_tag(wt: Path, tid: str, commit: str) -> tuple[str, bool]:
    """``(tag, is_new)``. Existing tag with the same tree → reused (no-op).
    Different tree → next free ``-<n>``; an existing snapshot is never lost."""
    base = f"{_TAG_PREFIX}/{tid}"
    new_tree = _tree_of(wt, commit)
    for n in range(_MAX_TAG_VARIANTS):
        tag = base if n == 0 else f"{base}-{n + 1}"
        existing = _tree_of(wt, f"refs/tags/{tag}")
        if not existing:
            return tag, True
        if existing == new_tree:
            return tag, False
    return f"{base}-{int(time.time())}", True


def autosave(locks_root: Path | str, tid: str, *, agent: str = "") -> str | None:
    """Snapshot the executor's recorded worktree and pin it under a
    ``wip-recovery`` tag; drop a breadcrumb for the queue to flush. Returns
    the tag, or ``None`` when there is nothing to save. Never raises.
    Safe to call while holding ``queue_lock`` — it does not touch the queue."""
    if _disabled():
        return None
    try:
        wt = read_worktree(locks_root, tid)
        if wt is None:
            return None
        message = f"wip-recovery {tid}" + (f" ({agent})" if agent else "")
        commit = _snapshot_commit(wt, message)
        if commit is None:
            return None
        tag, is_new = _pick_tag(wt, tid, commit)
        if is_new and _git(wt, "tag", "-f", tag, commit).returncode != 0:
            return None
        try:
            _breadcrumb(locks_root, tid).write_text(tag + "\n", encoding="utf-8")
        except OSError:
            pass
        return tag
    except Exception:  # pragma: no cover - never break lock cleanup
        return None


def flush_breadcrumb(locks_root: Path | str, active: Path | str, tid: str) -> str | None:
    """If an autosave breadcrumb exists for *tid*, write its tag into the
    task's ``resume:`` field and clear the breadcrumb. Returns the tag, or
    ``None``. Must be called OUTSIDE a held ``queue_lock``."""
    crumb = _breadcrumb(locks_root, tid)
    try:
        tag = crumb.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not tag:
        crumb.unlink(missing_ok=True)
        return None
    try:
        from . import taskfile

        taskfile.annotate_resume(
            Path(active), tid,
            f"WIP предыдущего исполнителя автосохранён при снятии лока. Начни с "
            f"`git cherry-pick -n {tag}` в системном чекауте (тег переживает "
            f"удаление worktree и /tmp), а не с чистого листа.",
        )
    except Exception:
        return None
    crumb.unlink(missing_ok=True)
    return tag


def evict(locks_root: Path | str, active: Path | str, tid: str, agent: str = "") -> str | None:
    """autosave + flush in one call, for callers that are not holding
    ``queue_lock`` (MCP cleanup, ``brain-lock`` shell-out)."""
    autosave(locks_root, tid, agent=agent)
    return flush_breadcrumb(locks_root, active, tid)


def _main(argv: list[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="brain_core.autosave")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--locks", required=True)
    r.add_argument("--tid", required=True)
    r.add_argument("--cwd", default=None)
    e = sub.add_parser("evict")
    e.add_argument("--locks", required=True)
    e.add_argument("--active", required=True)
    e.add_argument("--tid", required=True)
    e.add_argument("--agent", default="")
    a = p.parse_args(argv)
    if a.cmd == "record":
        record_worktree(a.locks, a.tid, a.cwd)
        return 0
    tag = evict(a.locks, a.active, a.tid, a.agent)
    if tag:
        print(tag)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
