"""Append-only merge for ``wiki/log.md``.

Rows are interleaved by timestamp. Duplicates collapse only when
(ts, operation, task-id, agent/node) *and* the remaining extra slot match.
Equal timestamps sort by (op, task-id, agent, node, extra, line) so the
result does not depend on which side a row arrived from.

The git merge driver ``brain-log`` is installed into a vault's conflict
workflow via ``.git/info/attributes`` and ``merge.brain-log.driver``.
``brain-federation sync`` installs the driver before pull --rebase and
resolves a leftover ``wiki/log.md`` conflict if the driver did not fire.
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

from brain_core import clock

from .git_ops import git_path, git_run, is_git_repo


GIT_DRIVER_NAME = "brain-log"
LOG_RELPATH = "wiki/log.md"
ATTRIBUTES_LINE = f"{LOG_RELPATH} merge={GIT_DRIVER_NAME}"

ENTRY_RE = re.compile(r"^## \[([^\]]+)\]\s+(\S+)(?:\s*\|\s*(.*))?$")
DASH_TS_RE = re.compile(r"^-\s+(\d{4}-\d{2}-\d{2}T\S+?)(?::\s|\s|$)")
NODE_RE = re.compile(r"(?:^|\|\s*)node=([^\s|]+)")


@dataclass(frozen=True)
class JournalRow:
    ts: str
    op: str
    task_id: str
    agent: str
    node: str
    extra: str
    text: str
    epoch: float

    @property
    def identity(self) -> tuple[str, str, str, str, str, str]:
        return (self.ts, self.op, self.task_id, self.agent, self.node, self.extra)

    @property
    def sort_key(self) -> tuple:
        return (
            self.epoch,
            self.ts,
            self.op,
            self.task_id,
            self.agent,
            self.node,
            self.extra,
            self.text,
        )


def _epoch(ts: str) -> float:
    dt = clock.parse(ts)
    if dt is None and ts and "T" in ts and not ts.endswith("Z") and "+" not in ts[-6:]:
        dt = clock.parse(ts + "Z")
    if dt is None:
        return float("inf")
    return dt.timestamp()


def _is_entry_line(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("## ["):
        return True
    return bool(DASH_TS_RE.match(stripped))


def _row_from_block(block: list[str]) -> JournalRow:
    header = block[0].rstrip()
    text = "\n".join(block).rstrip("\n")
    match = ENTRY_RE.match(header)
    if match:
        ts, op, rest = match.group(1), match.group(2), match.group(3) or ""
        parts = [p.strip() for p in rest.split(" | ")] if rest else []
        task_id = parts[0] if parts else ""
        agent = parts[1] if len(parts) > 1 else ""
        extra = " | ".join(parts[2:]) if len(parts) > 2 else ""
        node_match = NODE_RE.search(extra)
        node = node_match.group(1) if node_match else ""
        return JournalRow(
            ts=ts,
            op=op,
            task_id=task_id,
            agent=agent,
            node=node,
            extra=extra,
            text=text,
            epoch=_epoch(ts),
        )
    dash = DASH_TS_RE.match(header)
    ts = dash.group(1).rstrip(":") if dash else ""
    return JournalRow(
        ts=ts or header,
        op="",
        task_id="",
        agent="",
        node="",
        extra=text,
        text=text,
        epoch=_epoch(ts) if ts else float("inf"),
    )


def parse_journal(text: str) -> tuple[str, list[JournalRow]]:
    if not text:
        return "", []
    lines = text.splitlines()
    i = 0
    preamble_lines: list[str] = []
    while i < len(lines) and not _is_entry_line(lines[i]):
        preamble_lines.append(lines[i])
        i += 1
    rows: list[JournalRow] = []
    while i < len(lines):
        block = [lines[i]]
        i += 1
        while i < len(lines) and not _is_entry_line(lines[i]):
            block.append(lines[i])
            i += 1
        while block and block[-1].strip() == "":
            block.pop()
        if block:
            rows.append(_row_from_block(block))
    preamble = "\n".join(preamble_lines).rstrip("\n")
    return preamble, rows


def _render(preamble: str, rows: list[JournalRow]) -> str:
    pre = preamble.rstrip("\n")
    body = "\n".join(row.text.rstrip("\n") for row in rows)
    if pre and body:
        return pre + "\n\n" + body + "\n"
    if pre:
        return pre + "\n"
    if body:
        return body + "\n"
    return ""


def merge_journal(local: str, remote: str, base: str = "") -> str:
    """Union of journal rows, sorted by timestamp, with identity dedup.

    ``base`` is accepted for 3-way callers (git driver) but append-only
    merge is a commutative union of local and remote; deletions are not
    propagated.
    """
    del base  # append-only: keep anything still present on either side
    local_preamble, local_rows = parse_journal(local or "")
    remote_preamble, remote_rows = parse_journal(remote or "")
    preamble = local_preamble if local_preamble.strip() else remote_preamble
    seen: set[tuple[str, str, str, str, str, str]] = set()
    merged: list[JournalRow] = []
    for row in sorted((*local_rows, *remote_rows), key=lambda item: item.sort_key):
        if row.identity in seen:
            continue
        seen.add(row.identity)
        merged.append(row)
    return _render(preamble, merged)


def _read_journal_file(path: str | Path) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    target = Path(raw)
    if not target.is_file():
        return ""
    return target.read_text(encoding="utf-8", errors="replace")


def merge_journal_files(base: str | Path, local: str | Path, remote: str | Path) -> str:
    return merge_journal(
        _read_journal_file(local),
        _read_journal_file(remote),
        _read_journal_file(base),
    )


def git_driver(base: str, local: str, remote: str) -> int:
    """Git merge driver: write the merged journal onto ``local`` (%A)."""
    try:
        merged = merge_journal_files(base, local, remote)
        Path(local).write_text(merged, encoding="utf-8")
    except OSError:
        return 1
    return 0


def cmd_merge_log(args: argparse.Namespace) -> int:
    base = getattr(args, "base", "") or ""
    local = getattr(args, "local", "") or ""
    remote = getattr(args, "remote", "") or ""
    if not Path(str(local)).is_file() and not Path(str(remote)).is_file():
        print("brain-federation merge-log: missing local/remote journal", file=sys.stderr)
        return 2
    try:
        merged = merge_journal_files(base, local, remote)
    except OSError as exc:
        print(f"brain-federation merge-log: {exc}", file=sys.stderr)
        return 2
    out = getattr(args, "out", "") or ""
    if out:
        Path(out).write_text(merged, encoding="utf-8")
    else:
        sys.stdout.write(merged)
    return 0


def driver_command() -> str:
    lib = str(Path(__file__).resolve().parent.parent)
    return (
        f"env PYTHONPATH={shlex.quote(lib)} "
        f"{shlex.quote(sys.executable)} -m brain_federation.journal_merge %O %A %B"
    )


def install_log_merge_driver(repo: Path) -> None:
    """Wire the ``brain-log`` driver into this repo's conflict workflow."""
    if not is_git_repo(repo):
        return
    attrs = git_path(repo, "info/attributes")
    try:
        attrs.parent.mkdir(parents=True, exist_ok=True)
        existing = attrs.read_text(encoding="utf-8") if attrs.exists() else ""
        if ATTRIBUTES_LINE not in existing.splitlines():
            prefix = "" if not existing or existing.endswith("\n") else "\n"
            attrs.write_text(existing + prefix + ATTRIBUTES_LINE + "\n", encoding="utf-8")
        git_run(repo, "config", f"merge.{GIT_DRIVER_NAME}.name", "Brain wiki/log.md journal merge")
        git_run(repo, "config", f"merge.{GIT_DRIVER_NAME}.driver", driver_command())
    except OSError:
        return


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def rebase_in_progress(repo: Path) -> bool:
    return _path_exists(git_path(repo, "rebase-merge")) or _path_exists(
        git_path(repo, "rebase-apply")
    )


def unmerged_paths(repo: Path) -> list[str]:
    res = git_run(repo, "ls-files", "-u")
    found: list[str] = []
    seen: set[str] = set()
    for line in res.stdout.splitlines():
        if "\t" not in line:
            continue
        path = line.split("\t", 1)[1]
        if path not in seen:
            seen.add(path)
            found.append(path)
    return found


def _stage_text(repo: Path, stage: int, path: str) -> str:
    res = git_run(repo, "show", f":{stage}:{path}")
    return res.stdout if res.returncode == 0 else ""


def resolve_log_conflict(repo: Path) -> bool:
    """Merge unmerged ``wiki/log.md`` and ``git add`` it.

    Returns True only when that was the last remaining conflict.
    """
    paths = unmerged_paths(repo)
    if LOG_RELPATH not in paths:
        return False
    merged = merge_journal(
        _stage_text(repo, 2, LOG_RELPATH),
        _stage_text(repo, 3, LOG_RELPATH),
        _stage_text(repo, 1, LOG_RELPATH),
    )
    dest = repo / LOG_RELPATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(merged, encoding="utf-8")
    added = git_run(repo, "add", "--", LOG_RELPATH)
    if added.returncode != 0:
        return False
    remaining = [path for path in unmerged_paths(repo) if path != LOG_RELPATH]
    return remaining == []


def finish_rebase_resolving_log(repo: Path) -> bool:
    """Resolve ``wiki/log.md`` rebase conflicts and continue until clean."""
    if not rebase_in_progress(repo):
        return False
    env = os.environ.copy()
    env["GIT_EDITOR"] = "true"
    env["GIT_SEQUENCE_EDITOR"] = "true"
    for _ in range(50):
        if not rebase_in_progress(repo):
            return True
        if not resolve_log_conflict(repo):
            return False
        cont = git_run(
            repo,
            "-c",
            "core.editor=true",
            "rebase",
            "--continue",
            env=env,
        )
        if cont.returncode == 0:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) == 3 and not str(argv[0]).startswith("-"):
        return git_driver(argv[0], argv[1], argv[2])
    parser = argparse.ArgumentParser(prog="brain-federation merge-log")
    parser.add_argument("--base", default="", help="Common ancestor journal (git %O)")
    parser.add_argument("--local", required=True, help="Ours (git %A)")
    parser.add_argument("--remote", required=True, help="Theirs (git %B)")
    parser.add_argument("--out", default="", help="Write merged journal here (default: stdout)")
    args = parser.parse_args(argv)
    return cmd_merge_log(args)


if __name__ == "__main__":
    raise SystemExit(main())
