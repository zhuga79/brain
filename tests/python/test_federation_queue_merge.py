"""Auto task-queue merge on federation sync (federation s4).

tasks/active.md and tasks/done.md merge by task id. New ids from either side
survive; independent progress (state advance, one-sided field edit) merges
silently. A real disagreement stops the sync: the same task edited on both
sides in title/role/mode/acceptance, or an open/done split.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from brain_federation.queue_merge import (
    ACTIVE_RELPATH,
    DONE_RELPATH,
    finish_rebase_auto_resolve,
    merge_queue,
    resolve_queue_conflict,
)
from brain_federation.sync import cmd_sync


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class DummyArgs:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def _git(repo: Path, *args: str, check: bool = True, env: dict | None = None):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    merged.setdefault("GIT_AUTHOR_NAME", "Test")
    merged.setdefault("GIT_AUTHOR_EMAIL", "test@example.org")
    merged.setdefault("GIT_COMMITTER_NAME", "Test")
    merged.setdefault("GIT_COMMITTER_EMAIL", "test@example.org")
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check, capture_output=True, text=True, env=merged,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    _git(path, "config", "user.email", "test@example.org")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")
    return path


def _task(state: str, tid: str, title: str, *body: str) -> str:
    lines = [f"- [{state}] [P1] {tid} — {title}"]
    lines += [f"      {b}" for b in body]
    return "\n".join(lines)


def _active(*blocks: str) -> str:
    return "# Active Tasks\n\n" + "\n\n".join(blocks) + ("\n" if blocks else "")


def _done(*blocks: str) -> str:
    return "# Done tasks\n\n" + "\n\n".join(blocks) + ("\n" if blocks else "")


_HEAD_RE = re.compile(r"^- \[.\] \[[^\]]*\] (\S+)")


def _ids(text: str) -> list[str]:
    out = []
    for ln in text.splitlines():
        m = _HEAD_RE.match(ln)
        if m:
            out.append(m.group(1))
    return out


# ---------------------------------------------------------------------------
# merge_queue — unit
# ---------------------------------------------------------------------------

def test_new_id_from_each_side_is_kept():
    base = _active(_task(" ", "t-base", "Base", "role: developer"))
    local = _active(
        _task(" ", "t-base", "Base", "role: developer"),
        _task(" ", "t-local", "Local only", "role: developer"),
    )
    remote = _active(
        _task(" ", "t-base", "Base", "role: developer"),
        _task(" ", "t-remote", "Remote only", "role: developer"),
    )
    res = merge_queue(base, local, remote, "", "", "")
    assert res.conflicts == []
    assert set(_ids(res.active)) == {"t-base", "t-local", "t-remote"}


def test_identical_task_on_both_sides_kept_once():
    blk = _task("~", "t-x", "X", "role: developer", "started: 2026-08-16T00:00:00Z", "by: a")
    res = merge_queue(_active(blk), _active(blk), _active(blk), "", "", "")
    assert res.conflicts == []
    assert _ids(res.active) == ["t-x"]
    assert res.active.count("t-x — X") == 1


def test_state_progression_wins_over_open():
    base = _active(_task(" ", "t-x", "X", "role: developer"))
    local = _active(_task("~", "t-x", "X", "role: developer", "started: 2026-08-16T01:00:00Z", "by: alice"))
    remote = _active(_task(" ", "t-x", "X", "role: developer"))
    res = merge_queue(base, local, remote, "", "", "")
    assert res.conflicts == []
    assert res.active.splitlines()[2].startswith("- [~] [P1] t-x")
    assert "by: alice" in res.active


def test_one_sided_field_edit_is_taken():
    base = _active(_task(" ", "t-x", "Old title", "role: developer"))
    local = _active(_task(" ", "t-x", "Old title", "role: developer"))
    remote = _active(_task(" ", "t-x", "New remote title", "role: developer"))
    res = merge_queue(base, local, remote, "", "", "")
    assert res.conflicts == []
    assert "New remote title" in res.active


def test_field_divergence_is_a_blocking_conflict():
    base = _active(_task(" ", "t-x", "Base title", "role: developer"))
    local = _active(_task(" ", "t-x", "Local title", "role: developer"))
    remote = _active(_task(" ", "t-x", "Remote title", "role: developer"))
    res = merge_queue(base, local, remote, "", "", "")
    assert [c.kind for c in res.conflicts] == ["field-divergence"]
    assert res.conflicts[0].task_id == "t-x"
    assert "title" in res.conflicts[0].detail


def test_role_divergence_is_a_blocking_conflict():
    base = _active(_task(" ", "t-x", "X", "role: developer"))
    local = _active(_task(" ", "t-x", "X", "role: reviewer"))
    remote = _active(_task(" ", "t-x", "X", "role: architect"))
    res = merge_queue(base, local, remote, "", "", "")
    assert res.conflicts and res.conflicts[0].kind == "field-divergence"
    assert "role" in res.conflicts[0].detail


def test_active_done_split_is_a_blocking_conflict():
    blk_open = _task(" ", "t-x", "X", "role: developer")
    blk_done = _task("x", "t-x", "X", "role: developer", "by: alice", "model: openai-gpt-5.4")
    # local completed it, remote still has it open
    res = merge_queue(
        base_active=_active(blk_open), local_active=_active(), remote_active=_active(blk_open),
        base_done="", local_done=_done(blk_done), remote_done="",
    )
    assert [c.kind for c in res.conflicts] == ["active-done-split"]
    assert res.conflicts[0].task_id == "t-x"


def test_no_task_lost_when_deleted_on_one_side():
    base = _active(_task(" ", "t-keep", "Keep", "role: developer"))
    local = _active()  # deleted locally
    remote = _active(_task(" ", "t-keep", "Keep", "role: developer"))
    res = merge_queue(base, local, remote, "", "", "")
    assert res.conflicts == []
    assert "t-keep" in _ids(res.active)


def test_header_is_preserved():
    local = "# My Custom Active Header\n\n" + _task(" ", "t-x", "X", "role: developer") + "\n"
    remote = _active(_task(" ", "t-y", "Y", "role: developer"))
    res = merge_queue(local, local, remote, "", "", "")
    assert res.active.startswith("# My Custom Active Header")
    assert set(_ids(res.active)) == {"t-x", "t-y"}


def test_result_is_side_independent():
    base = _active(_task(" ", "t-base", "Base", "role: developer"))
    a = _active(_task(" ", "t-base", "Base", "role: developer"), _task(" ", "t-a", "A", "role: developer"))
    b = _active(_task(" ", "t-base", "Base", "role: developer"), _task(" ", "t-b", "B", "role: developer"))
    left = merge_queue(base, a, b, "", "", "")
    right = merge_queue(base, b, a, "", "", "")
    assert set(_ids(left.active)) == set(_ids(right.active))
    assert left.conflicts == right.conflicts == []


# ---------------------------------------------------------------------------
# resolve_queue_conflict / finish_rebase_auto_resolve — real git
# ---------------------------------------------------------------------------

def _seed(repo: Path) -> None:
    (repo / "tasks").mkdir(parents=True, exist_ok=True)
    (repo / "wiki").mkdir(parents=True, exist_ok=True)
    (repo / ACTIVE_RELPATH).write_text(
        _active(_task(" ", "t-base", "Base", "role: developer")), encoding="utf-8"
    )
    (repo / DONE_RELPATH).write_text(_done(), encoding="utf-8")
    (repo / "wiki" / "log.md").write_text("# Log\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")


def test_resolve_queue_conflict_merges_and_stages(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _seed(repo)

    _git(repo, "checkout", "-qb", "onto")
    (repo / ACTIVE_RELPATH).write_text(
        _active(
            _task(" ", "t-base", "Base", "role: developer"),
            _task(" ", "t-onto", "From onto", "role: developer"),
        ),
        encoding="utf-8",
    )
    _git(repo, "commit", "-aqm", "onto")

    _git(repo, "checkout", "-q", "main")
    (repo / ACTIVE_RELPATH).write_text(
        _active(
            _task(" ", "t-base", "Base", "role: developer"),
            _task("~", "t-topic", "From topic", "role: developer", "by: bob"),
        ),
        encoding="utf-8",
    )
    _git(repo, "commit", "-aqm", "topic")

    rebase = _git(repo, "rebase", "onto", check=False)
    assert rebase.returncode != 0

    res = resolve_queue_conflict(repo)
    assert res.conflicts == []
    assert res.touched
    text = (repo / ACTIVE_RELPATH).read_text(encoding="utf-8")
    assert set(_ids(text)) == {"t-base", "t-onto", "t-topic"}
    assert "<<<<<<<" not in text
    staged = _git(repo, "diff", "--cached", "--name-only").stdout.split()
    assert ACTIVE_RELPATH in staged


def test_cmd_sync_auto_merges_task_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_NODE_ID", "sync-node")
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)

    a = _init_repo(tmp_path / "a")
    _git(a, "remote", "add", "origin", str(bare))
    _seed(a)
    _git(a, "push", "-u", "origin", "main")

    b = tmp_path / "b"
    subprocess.run(["git", "clone", "-q", str(bare), str(b)], check=True)
    _git(b, "config", "user.email", "test@example.org")
    _git(b, "config", "user.name", "Test")
    _git(b, "config", "commit.gpgsign", "false")

    (a / ACTIVE_RELPATH).write_text(
        _active(
            _task(" ", "t-base", "Base", "role: developer"),
            _task(" ", "t-from-a", "From A", "role: developer"),
        ),
        encoding="utf-8",
    )
    _git(a, "commit", "-aqm", "a-task")
    _git(a, "push")

    (b / ACTIVE_RELPATH).write_text(
        _active(
            _task("~", "t-base", "Base", "role: developer", "by: bob"),
            _task(" ", "t-from-b", "From B", "role: developer"),
        ),
        encoding="utf-8",
    )
    _git(b, "commit", "-aqm", "b-task")

    args = DummyArgs(repo=str(b), brain=str(b), json=True)
    assert cmd_sync(args) == 0
    text = (b / ACTIVE_RELPATH).read_text(encoding="utf-8")
    assert set(_ids(text)) == {"t-base", "t-from-a", "t-from-b"}
    assert "<<<<<<<" not in text
    assert "- [~] [P1] t-base" in text  # b's progression survived


def test_cmd_sync_blocks_on_field_divergence(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BRAIN_NODE_ID", "sync-node")
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)

    a = _init_repo(tmp_path / "a")
    _git(a, "remote", "add", "origin", str(bare))
    _seed(a)
    _git(a, "push", "-u", "origin", "main")

    b = tmp_path / "b"
    subprocess.run(["git", "clone", "-q", str(bare), str(b)], check=True)
    _git(b, "config", "user.email", "test@example.org")
    _git(b, "config", "user.name", "Test")
    _git(b, "config", "commit.gpgsign", "false")

    (a / ACTIVE_RELPATH).write_text(
        _active(_task(" ", "t-base", "Title from A", "role: developer")), encoding="utf-8"
    )
    _git(a, "commit", "-aqm", "a-title")
    _git(a, "push")

    (b / ACTIVE_RELPATH).write_text(
        _active(_task(" ", "t-base", "Title from B", "role: developer")), encoding="utf-8"
    )
    _git(b, "commit", "-aqm", "b-title")

    args = DummyArgs(repo=str(b), brain=str(b), json=True)
    rc = cmd_sync(args)
    assert rc != 0
    out = capsys.readouterr().out
    assert "federation-sync-queue-conflict" in out
    assert "field-divergence" in out
    # rebase aborted: no rebase in progress, active.md unmodified, no markers
    assert not (b / ".git" / "rebase-merge").exists()
    assert not (b / ".git" / "rebase-apply").exists()
    assert _git(b, "status", "--porcelain", "--", ACTIVE_RELPATH).stdout.strip() == ""
    assert "<<<<<<<" not in (b / ACTIVE_RELPATH).read_text(encoding="utf-8")


def test_finish_rebase_auto_resolve_no_rebase_is_noop(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _seed(repo)
    ok, conflicts = finish_rebase_auto_resolve(repo)
    assert ok is False and conflicts == []
