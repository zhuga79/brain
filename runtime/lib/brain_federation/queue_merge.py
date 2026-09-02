"""Task-queue merge for federation rebase conflicts.

``tasks/active.md`` and ``tasks/done.md`` are merged by task id. A task
present on either side is kept — federation never drops a task. Changes that
progress independently (state advance, one-sided field edit, dependency
additions) merge automatically. Two divergences stop the sync for a human:

* the same task edited on both sides in ``title``, ``role``, ``mode`` or
  ``acceptance`` (a real disagreement, not a progression);
* a task that is open on one side and done on the other (active/done split).

``brain-federation sync`` resolves these during ``pull --rebase`` alongside
the ``wiki/log.md`` journal merge; a blocking divergence aborts the rebase.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import brain_task_parser

from .git_ops import git_run
from .journal_merge import (
    LOG_RELPATH,
    rebase_in_progress,
    resolve_log_conflict,
    unmerged_paths,
    _stage_text,
)

ACTIVE_RELPATH = "tasks/active.md"
DONE_RELPATH = "tasks/done.md"
QUEUE_RELPATHS = (ACTIVE_RELPATH, DONE_RELPATH)

FIELD_KEYS = ("title", "role", "mode", "acceptance")
_STATE_RANK = {"x": 4, "~": 3, "!": 2, " ": 1, "": 0}


@dataclass(frozen=True)
class QueueConflict:
    task_id: str
    kind: str  # "field-divergence" | "active-done-split"
    detail: str


@dataclass
class QueueMergeResult:
    active: str
    done: str
    conflicts: list[QueueConflict] = field(default_factory=list)
    touched: bool = False


def _default_header(loc: str) -> str:
    return "# Active Tasks" if loc == "active" else "# Done tasks"


def _split_header(text: str) -> tuple[str, str]:
    """Preamble (everything before the first task block) and the rest."""
    if not text:
        return "", ""
    blocks = brain_task_parser.find_blocks(text)
    if not blocks:
        return text.rstrip("\n"), ""
    idx = text.find(blocks[0])
    return text[:idx].rstrip("\n"), text[idx:]


def _index(active_text: str, done_text: str) -> dict[str, tuple[str, dict, str]]:
    """id -> (raw block, parsed dict, "active" | "done"). Later wins on dup id."""
    out: dict[str, tuple[str, dict, str]] = {}
    for text, loc in ((active_text or "", "active"), (done_text or "", "done")):
        for raw in brain_task_parser.find_blocks(text):
            parsed = brain_task_parser.parse_block(raw)
            tid = parsed.get("id")
            if tid:
                out[tid] = (raw.rstrip("\n"), parsed, loc)
    return out


def _render(preamble: str, blocks: list[str], fallback_loc: str) -> str:
    pre = preamble.strip() or _default_header(fallback_loc)
    body = "\n\n".join(b.rstrip("\n") for b in blocks)
    if body:
        return pre + "\n\n" + body + "\n"
    return pre + "\n"


def merge_queue(
    base_active: str,
    local_active: str,
    remote_active: str,
    base_done: str,
    local_done: str,
    remote_done: str,
) -> QueueMergeResult:
    base = _index(base_active, base_done)
    local = _index(local_active, local_done)
    remote = _index(remote_active, remote_done)

    order = list(local) + [tid for tid in remote if tid not in local]
    conflicts: list[QueueConflict] = []
    picked: dict[str, tuple[str, str]] = {}  # id -> (raw, loc)

    for tid in order:
        l = local.get(tid)
        r = remote.get(tid)
        b = base.get(tid)

        if l and not r:
            picked[tid] = (l[0], l[2])
            continue
        if r and not l:
            picked[tid] = (r[0], r[2])
            continue

        lraw, lp, lloc = l  # type: ignore[misc]
        rraw, rp, rloc = r  # type: ignore[misc]

        if lraw == rraw:
            picked[tid] = (lraw, lloc)
            continue

        if lloc != rloc:
            conflicts.append(QueueConflict(
                tid, "active-done-split",
                f"{lloc} on this node, {rloc} on the remote",
            ))
            picked[tid] = (lraw, lloc)  # keep something so no task vanishes
            continue

        bp = b[1] if b else {}
        divergent = [
            k for k in FIELD_KEYS
            if lp.get(k, "") != rp.get(k, "")
            and lp.get(k, "") != bp.get(k, "")
            and rp.get(k, "") != bp.get(k, "")
        ]
        if divergent:
            conflicts.append(QueueConflict(
                tid, "field-divergence",
                "both sides changed " + ", ".join(divergent),
            ))
            picked[tid] = (lraw, lloc)
            continue

        lr = _STATE_RANK.get(lp.get("state", ""), 0)
        rr = _STATE_RANK.get(rp.get("state", ""), 0)
        if rr > lr:
            picked[tid] = (rraw, rloc)
        elif lr > rr:
            picked[tid] = (lraw, lloc)
        else:
            l_changed = (b is None) or lraw != b[0]
            r_changed = (b is None) or rraw != b[0]
            if r_changed and not l_changed:
                picked[tid] = (rraw, rloc)
            else:
                picked[tid] = (lraw, lloc)

    active_pre, _ = _split_header(local_active or remote_active)
    done_pre, _ = _split_header(local_done or remote_done)
    active_blocks = [raw for tid in order for raw, loc in [picked[tid]] if loc == "active"]
    done_blocks = [raw for tid in order for raw, loc in [picked[tid]] if loc == "done"]

    return QueueMergeResult(
        active=_render(active_pre, active_blocks, "active"),
        done=_render(done_pre, done_blocks, "done"),
        conflicts=conflicts,
        touched=True,
    )


def _three_way_text(repo: Path, rel: str, unmerged: list[str]) -> tuple[str, str, str]:
    """(base, local, remote) text for a path. Non-conflicted paths read the
    worktree for all three slots so merge_queue sees no change there."""
    if rel in unmerged:
        return (
            _stage_text(repo, 1, rel),
            _stage_text(repo, 2, rel),
            _stage_text(repo, 3, rel),
        )
    try:
        current = (repo / rel).read_text(encoding="utf-8")
    except OSError:
        current = ""
    return current, current, current


def resolve_queue_conflict(repo: Path) -> QueueMergeResult:
    """Merge unmerged ``tasks/active.md`` / ``tasks/done.md`` and ``git add``.

    Returns the merge result. ``conflicts`` non-empty means the queue could
    not be auto-resolved and nothing was staged.
    """
    unmerged = unmerged_paths(repo)
    if not any(rel in unmerged for rel in QUEUE_RELPATHS):
        return QueueMergeResult(active="", done="", conflicts=[], touched=False)

    ba, la, ra = _three_way_text(repo, ACTIVE_RELPATH, unmerged)
    bd, ld, rd = _three_way_text(repo, DONE_RELPATH, unmerged)
    merged = merge_queue(ba, la, ra, bd, ld, rd)
    if merged.conflicts:
        return merged

    # A non-conflicting merge never moves a task between the two files (an
    # active/done split is a hard conflict), so only the files that actually
    # conflicted need rewriting.
    for rel, text in ((ACTIVE_RELPATH, merged.active), (DONE_RELPATH, merged.done)):
        if rel not in unmerged:
            continue
        dest = repo / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        git_run(repo, "add", "--", rel)
    return merged


def finish_rebase_auto_resolve(repo: Path) -> tuple[bool, list[QueueConflict]]:
    """Auto-resolve wiki/log.md + task-queue rebase conflicts, continue until
    clean. Returns (ok, blocking_queue_conflicts). A blocking divergence aborts
    the rebase so the working tree is left clean for a human."""
    if not rebase_in_progress(repo):
        return (False, [])
    env = os.environ.copy()
    env["GIT_EDITOR"] = "true"
    env["GIT_SEQUENCE_EDITOR"] = "true"
    for _ in range(50):
        if not rebase_in_progress(repo):
            return (True, [])
        unmerged = unmerged_paths(repo)
        auto: set[str] = set()
        if LOG_RELPATH in unmerged:
            resolve_log_conflict(repo)  # side effect: merge + git add log
            auto.add(LOG_RELPATH)
        qres = resolve_queue_conflict(repo)
        if qres.conflicts:
            git_run(repo, "rebase", "--abort")
            return (False, qres.conflicts)
        if qres.touched:
            auto |= set(QUEUE_RELPATHS)
        remaining = [p for p in unmerged_paths(repo) if p not in auto]
        if remaining:
            return (False, [])
        cont = git_run(
            repo, "-c", "core.editor=true", "rebase", "--continue", env=env,
        )
        if cont.returncode == 0:
            return (True, [])
    return (False, [])
