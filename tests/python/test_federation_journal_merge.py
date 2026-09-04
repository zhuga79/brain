"""Deterministic wiki/log.md merge with dedup (federation s3).

Append-only interleaving by timestamp; rows with the same
(ts, operation, task-id, agent/node) collapse to one; equal timestamps
sort by a key that does not depend on which side the row came from.
Similar-but-not-identical rows (different agent, node, task id, or extra)
are kept. The git merge driver `brain-log` is installed into the repo's
conflict workflow (`.git/info/attributes` + `merge.brain-log.driver`).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from brain_federation.journal_merge import (
    GIT_DRIVER_NAME,
    LOG_RELPATH,
    install_log_merge_driver,
    merge_journal,
    resolve_log_conflict,
)
from brain_federation.sync import cmd_sync


REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "runtime" / "lib"
BIN = REPO / "runtime" / "bin"

T0 = "2026-08-16T10:00:00Z"
T1 = "2026-08-16T10:01:00Z"
T2 = "2026-08-16T10:02:00Z"


def _row(
    ts: str,
    op: str = "task-start",
    task_id: str = "t-1",
    agent: str = "alice",
    extra: str = "node=n1",
) -> str:
    return f"## [{ts}] {op} | {task_id} | {agent} | {extra}"


def _log(*rows: str, preamble: str = "# Log\n") -> str:
    body = "\n".join(rows)
    if body:
        return f"{preamble}\n{body}\n"
    return preamble if preamble.endswith("\n") else preamble + "\n"


def _ids(text: str) -> list[str]:
    found: list[str] = []
    for line in text.splitlines():
        if not line.startswith("## ["):
            continue
        parts = line.split(" | ")
        found.append(parts[1].strip() if len(parts) > 1 else line)
    return found


def _ops(text: str) -> list[str]:
    found: list[str] = []
    for line in text.splitlines():
        if not line.startswith("## ["):
            continue
        head = line.split(" | ", 1)[0]
        found.append(head.rsplit(" ", 1)[-1])
    return found


class DummyArgs:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


# ---------------------------------------------------------------------------
# merge_journal: empty / preamble / union
# ---------------------------------------------------------------------------

def test_merge_empty_journals():
    assert merge_journal("", "") == ""
    assert merge_journal("# Log\n", "# Log\n") == "# Log\n"


def test_merge_none_like_empty_strings():
    assert merge_journal("", "# Log\n") == "# Log\n"
    assert merge_journal("# Log\n", "") == "# Log\n"


def test_merge_keeps_preamble_and_unions_new_rows():
    local = _log(_row(T1, task_id="t-local"))
    remote = _log(_row(T2, task_id="t-remote", agent="bob", extra="node=n2"))
    merged = merge_journal(local, remote)
    assert merged.startswith("# Log")
    assert _ids(merged) == ["t-local", "t-remote"]


# ---------------------------------------------------------------------------
# Dedup of identical (ts, op, task-id, agent/node)
# ---------------------------------------------------------------------------

def test_dedup_identical_rows_from_both_sides():
    shared = _row(T0, task_id="t-shared")
    local = _log(shared, _row(T1, task_id="t-local"))
    remote = _log(shared, _row(T2, task_id="t-remote", agent="bob", extra="node=n2"))
    merged = merge_journal(local, remote)
    assert merged.count(shared) == 1
    assert _ids(merged) == ["t-shared", "t-local", "t-remote"]


def test_dedup_identical_row_repeated_on_one_side():
    row = _row(T0)
    local = _log(row, row)
    remote = _log(row)
    merged = merge_journal(local, remote)
    assert merged.count(row) == 1
    assert _ids(merged) == ["t-1"]


def test_dedup_ignores_which_side_is_local():
    shared = _row(T0, task_id="t-shared")
    a = _log(shared, _row(T1, task_id="t-a"))
    b = _log(shared, _row(T2, task_id="t-b", agent="bob", extra="node=n2"))
    assert merge_journal(a, b) == merge_journal(b, a)


# ---------------------------------------------------------------------------
# Timestamp order, including equal-ts determinism
# ---------------------------------------------------------------------------

def test_interleave_by_timestamp_not_by_side():
    local = _log(_row(T2, task_id="t-late"))
    remote = _log(_row(T0, task_id="t-early", agent="bob", extra="node=n2"))
    merged = merge_journal(local, remote)
    assert _ids(merged) == ["t-early", "t-late"]
    swapped = merge_journal(remote, local)
    assert _ids(swapped) == ["t-early", "t-late"]


def test_equal_timestamp_order_is_deterministic():
    # Same ts, different ops: lexicographic op then task-id then agent/node.
    done = _row(T0, op="task-done", task_id="t-1", agent="alice")
    start = _row(T0, op="task-start", task_id="t-1", agent="alice")
    local = _log(start)
    remote = _log(done)
    merged = merge_journal(local, remote)
    assert _ops(merged) == ["task-done", "task-start"]
    assert merge_journal(remote, local) == merged


def test_equal_timestamp_different_task_ids_sorted():
    a = _row(T0, task_id="t-b", agent="alice")
    b = _row(T0, task_id="t-a", agent="bob", extra="node=n2")
    merged = merge_journal(_log(a), _log(b))
    assert _ids(merged) == ["t-a", "t-b"]
    assert merge_journal(_log(b), _log(a)) == merged


# ---------------------------------------------------------------------------
# Similar-but-not-identical rows stay
# ---------------------------------------------------------------------------

def test_similar_different_agent_kept():
    a = _row(T0, task_id="t-1", agent="alice", extra="node=n1")
    b = _row(T0, task_id="t-1", agent="bob", extra="node=n1")
    merged = merge_journal(_log(a), _log(b))
    assert a in merged and b in merged
    assert merged.count("## [") == 2


def test_similar_different_node_kept():
    a = _row(T0, task_id="t-1", agent="alice", extra="node=n1")
    b = _row(T0, task_id="t-1", agent="alice", extra="node=n2")
    merged = merge_journal(_log(a), _log(b))
    assert a in merged and b in merged
    assert merged.count("## [") == 2


def test_similar_different_task_id_kept():
    a = _row(T0, task_id="t-1", agent="alice")
    b = _row(T0, task_id="t-2", agent="alice")
    merged = merge_journal(_log(a), _log(b))
    assert _ids(merged) == ["t-1", "t-2"]


def test_similar_different_operation_kept():
    a = _row(T0, op="task-start", task_id="t-1")
    b = _row(T0, op="task-done", task_id="t-1")
    merged = merge_journal(_log(a), _log(b))
    assert merged.count("## [") == 2


def test_similar_different_extra_kept():
    a = _row(T0, extra="node=n1 | status=ok")
    b = _row(T0, extra="node=n1 | status=pull-failed")
    merged = merge_journal(_log(a), _log(b))
    assert a in merged and b in merged


def test_similar_agent_without_node_not_collapsed_into_noded_row():
    a = _row(T0, agent="alice", extra="")
    b = _row(T0, agent="alice", extra="node=n1")
    merged = merge_journal(_log(a), _log(b))
    assert merged.count("## [") == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_unicode_and_emoji_in_extra_are_preserved():
    row = _row(T0, extra="node=n1 | note=проверка 🧠")
    merged = merge_journal(_log(row), _log(row))
    assert "проверка 🧠" in merged
    assert merged.count(row) == 1


def test_unparseable_timestamp_still_kept():
    weird = "## [not-a-ts] lint |  | alice | node=n1"
    normal = _row(T0)
    merged = merge_journal(_log(normal), _log(weird))
    assert weird in merged
    assert normal in merged


def test_historical_dash_lines_are_kept_and_deduped():
    dash = "- 2026-07-07T00:00:00: provider-probe: OK"
    local = "# Log\n" + dash + "\n" + _row(T0) + "\n"
    remote = "# Log\n" + dash + "\n" + _row(T1, task_id="t-2") + "\n"
    merged = merge_journal(local, remote)
    assert merged.count(dash) == 1
    assert _ids(merged) == ["t-1", "t-2"]


def test_three_way_union_does_not_drop_side_additions(tmp_path):
    base = _log(_row(T0, task_id="t-base"))
    local = _log(_row(T0, task_id="t-base"), _row(T1, task_id="t-local"))
    remote = _log(_row(T0, task_id="t-base"), _row(T2, task_id="t-remote", agent="bob"))
    merged = merge_journal(local, remote, base)
    assert _ids(merged) == ["t-base", "t-local", "t-remote"]


def test_large_journal_stays_sorted_and_unique():
    local_rows = [_row(f"2026-08-16T10:{i:02d}:00Z", task_id=f"t-l{i}") for i in range(0, 80, 2)]
    remote_rows = [_row(f"2026-08-16T10:{i:02d}:00Z", task_id=f"t-r{i}", agent="bob") for i in range(1, 80, 2)]
    overlap = _row(T0, task_id="t-shared")
    local = _log(overlap, *local_rows)
    remote = _log(overlap, *remote_rows)
    merged = merge_journal(local, remote)
    entries = [ln for ln in merged.splitlines() if ln.startswith("## [")]
    assert len(entries) == 1 + len(local_rows) + len(remote_rows)
    stamps = [ln[4:ln.index("]")] for ln in entries]
    assert stamps == sorted(stamps)


# ---------------------------------------------------------------------------
# Git driver / conflict workflow
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    merged_env.setdefault("GIT_AUTHOR_NAME", "Test")
    merged_env.setdefault("GIT_AUTHOR_EMAIL", "test@example.org")
    merged_env.setdefault("GIT_COMMITTER_NAME", "Test")
    merged_env.setdefault("GIT_COMMITTER_EMAIL", "test@example.org")
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        env=merged_env,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    _git(path, "config", "user.email", "test@example.org")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")
    return path


def test_install_log_merge_driver_wires_git_attributes_and_config(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    install_log_merge_driver(repo)
    attrs = _git(repo, "rev-parse", "--git-path", "info/attributes").stdout.strip()
    attrs_path = Path(attrs) if Path(attrs).is_absolute() else repo / attrs
    text = attrs_path.read_text(encoding="utf-8")
    assert f"{LOG_RELPATH} merge={GIT_DRIVER_NAME}" in text
    driver = _git(repo, "config", "--get", f"merge.{GIT_DRIVER_NAME}.driver").stdout.strip()
    assert "%O" in driver and "%A" in driver and "%B" in driver
    assert "journal_merge" in driver or "merge-log" in driver


def test_git_merge_driver_resolves_wiki_log_conflict(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    log = repo / LOG_RELPATH
    log.parent.mkdir(parents=True)
    log.write_text(_log(_row(T0, task_id="t-base")), encoding="utf-8")
    _git(repo, "add", LOG_RELPATH)
    _git(repo, "commit", "-qm", "base")
    install_log_merge_driver(repo)

    _git(repo, "checkout", "-qb", "side")
    log.write_text(
        _log(_row(T0, task_id="t-base"), _row(T2, task_id="t-side", agent="bob", extra="node=n2")),
        encoding="utf-8",
    )
    _git(repo, "add", LOG_RELPATH)
    _git(repo, "commit", "-qm", "side")

    _git(repo, "checkout", "-q", "main")
    log.write_text(
        _log(_row(T0, task_id="t-base"), _row(T1, task_id="t-main")),
        encoding="utf-8",
    )
    _git(repo, "add", LOG_RELPATH)
    _git(repo, "commit", "-qm", "main")

    merged_proc = _git(repo, "merge", "side", "--no-edit", check=False)
    assert merged_proc.returncode == 0, merged_proc.stderr + merged_proc.stdout
    text = log.read_text(encoding="utf-8")
    assert _ids(text) == ["t-base", "t-main", "t-side"]
    assert text.count(_row(T0, task_id="t-base")) == 1
    assert "<<<<<<<" not in text


def test_resolve_log_conflict_during_rebase(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    log = repo / LOG_RELPATH
    log.parent.mkdir(parents=True)
    log.write_text(_log(_row(T0, task_id="t-base")), encoding="utf-8")
    _git(repo, "add", LOG_RELPATH)
    _git(repo, "commit", "-qm", "base")

    _git(repo, "checkout", "-qb", "onto")
    log.write_text(
        _log(_row(T0, task_id="t-base"), _row(T1, task_id="t-onto")),
        encoding="utf-8",
    )
    _git(repo, "add", LOG_RELPATH)
    _git(repo, "commit", "-qm", "onto")

    _git(repo, "checkout", "-q", "main")
    log.write_text(
        _log(_row(T0, task_id="t-base"), _row(T2, task_id="t-topic", agent="bob")),
        encoding="utf-8",
    )
    _git(repo, "add", LOG_RELPATH)
    _git(repo, "commit", "-qm", "topic")

    # Rebase main onto onto without the driver — conflict, then helper resolves.
    rebase = _git(repo, "rebase", "onto", check=False)
    assert rebase.returncode != 0
    assert resolve_log_conflict(repo) is True
    text = log.read_text(encoding="utf-8")
    assert _ids(text) == ["t-base", "t-onto", "t-topic"]
    _git(repo, "-c", "core.editor=true", "rebase", "--continue", env={"GIT_EDITOR": "true"})
    assert "<<<<<<<" not in log.read_text(encoding="utf-8")


def test_cmd_sync_resolves_wiki_log_rebase_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_NODE_ID", "sync-node")
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)

    a = _init_repo(tmp_path / "a")
    _git(a, "remote", "add", "origin", str(bare))
    log_a = a / LOG_RELPATH
    log_a.parent.mkdir(parents=True)
    log_a.write_text(_log(_row(T0, task_id="t-base")), encoding="utf-8")
    _git(a, "add", LOG_RELPATH)
    _git(a, "commit", "-qm", "base")
    _git(a, "push", "-u", "origin", "main")

    b = tmp_path / "b"
    subprocess.run(["git", "clone", "-q", str(bare), str(b)], check=True)
    _git(b, "config", "user.email", "test@example.org")
    _git(b, "config", "user.name", "Test")
    _git(b, "config", "commit.gpgsign", "false")

    log_a.write_text(
        _log(_row(T0, task_id="t-base"), _row(T1, task_id="t-from-a")),
        encoding="utf-8",
    )
    _git(a, "add", LOG_RELPATH)
    _git(a, "commit", "-qm", "a-append")
    _git(a, "push")

    log_b = b / LOG_RELPATH
    log_b.write_text(
        _log(_row(T0, task_id="t-base"), _row(T2, task_id="t-from-b", agent="bob", extra="node=n2")),
        encoding="utf-8",
    )
    _git(b, "add", LOG_RELPATH)
    _git(b, "commit", "-qm", "b-append")

    args = DummyArgs(repo=str(b), brain=str(b), json=True)
    assert cmd_sync(args) == 0
    text = log_b.read_text(encoding="utf-8")
    ids = _ids(text)
    assert ids[:3] == ["t-base", "t-from-a", "t-from-b"]
    assert "<<<<<<<" not in text
    assert "federation-sync" in text
    # Driver is wired for the next conflict too.
    driver = _git(b, "config", "--get", f"merge.{GIT_DRIVER_NAME}.driver").stdout.strip()
    assert driver


def test_cmd_merge_log_cli_writes_out(tmp_path):
    base = tmp_path / "base.md"
    local = tmp_path / "local.md"
    remote = tmp_path / "remote.md"
    out = tmp_path / "out.md"
    base.write_text(_log(_row(T0, task_id="t-base")), encoding="utf-8")
    local.write_text(_log(_row(T0, task_id="t-base"), _row(T1, task_id="t-local")), encoding="utf-8")
    remote.write_text(
        _log(_row(T0, task_id="t-base"), _row(T2, task_id="t-remote", agent="bob")),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(LIB)
    proc = subprocess.run(
        [
            sys.executable,
            str(BIN / "brain-federation"),
            "merge-log",
            "--base", str(base),
            "--local", str(local),
            "--remote", str(remote),
            "--out", str(out),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert _ids(out.read_text(encoding="utf-8")) == ["t-base", "t-local", "t-remote"]


def test_git_driver_positional_overwrites_local(tmp_path):
    from brain_federation.journal_merge import git_driver

    base = tmp_path / "O"
    local = tmp_path / "A"
    remote = tmp_path / "B"
    base.write_text(_log(_row(T0, task_id="t-base")), encoding="utf-8")
    local.write_text(_log(_row(T0, task_id="t-base"), _row(T2, task_id="t-late")), encoding="utf-8")
    remote.write_text(
        _log(_row(T0, task_id="t-base"), _row(T1, task_id="t-mid", agent="bob")),
        encoding="utf-8",
    )
    assert git_driver(str(base), str(local), str(remote)) == 0
    assert _ids(local.read_text(encoding="utf-8")) == ["t-base", "t-mid", "t-late"]


def test_git_driver_refuses_a_merge_that_drops_rows(tmp_path, monkeypatch):
    """A stale/broken merge_journal that loses history must not be written.

    The driver reparses its own output and refuses (rc 1, %A untouched) so
    git leaves the conflict instead of committing a truncated journal
    (t-2026-09-04-brain-sync-cycle-wiki-log-md-g).
    """
    from brain_federation import journal_merge as jm

    base = tmp_path / "O"
    local = tmp_path / "A"
    remote = tmp_path / "B"
    base.write_text("", encoding="utf-8")
    intact = _log(_row(T0, task_id="t-a"), _row(T1, task_id="t-b"))
    local.write_text(intact, encoding="utf-8")
    remote.write_text(_log(_row(T2, task_id="t-c", agent="bob")), encoding="utf-8")

    monkeypatch.setattr(jm, "merge_journal", lambda *a, **k: "# Log\n")

    assert jm.git_driver(str(base), str(local), str(remote)) == 1
    assert local.read_text(encoding="utf-8") == intact


def test_resolve_log_conflict_refuses_a_lossy_merge(tmp_path, monkeypatch):
    from brain_federation import journal_merge as jm

    repo = _init_repo(tmp_path / "repo")
    log = repo / LOG_RELPATH
    log.parent.mkdir(parents=True)
    log.write_text(_log(_row(T0, task_id="t-base")), encoding="utf-8")
    _git(repo, "add", LOG_RELPATH)
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "other")
    log.write_text(_log(_row(T0, task_id="t-base"), _row(T2, task_id="t-remote", agent="bob")), encoding="utf-8")
    _git(repo, "commit", "-qam", "remote")
    _git(repo, "checkout", "-q", "main")
    log.write_text(_log(_row(T0, task_id="t-base"), _row(T1, task_id="t-local")), encoding="utf-8")
    _git(repo, "commit", "-qam", "local")
    assert _git(repo, "merge", "other", check=False).returncode != 0  # real conflict staged

    monkeypatch.setattr(jm, "merge_journal", lambda *a, **k: "")
    assert resolve_log_conflict(repo) is False


def test_cmd_merge_log_missing_file_exits_2(tmp_path):
    from brain_federation.journal_merge import cmd_merge_log

    args = DummyArgs(
        base=str(tmp_path / "missing.md"),
        local=str(tmp_path / "missing.md"),
        remote=str(tmp_path / "missing.md"),
        out="",
    )
    assert cmd_merge_log(args) == 2


def test_merge_journal_files_empty_base_is_not_cwd(tmp_path):
    from brain_federation.journal_merge import merge_journal_files

    local = tmp_path / "local.md"
    remote = tmp_path / "remote.md"
    local.write_text(_log(_row(T1, task_id="t-l")), encoding="utf-8")
    remote.write_text(_log(_row(T0, task_id="t-r", agent="bob")), encoding="utf-8")
    merged = merge_journal_files("", str(local), str(remote))
    assert _ids(merged) == ["t-r", "t-l"]
