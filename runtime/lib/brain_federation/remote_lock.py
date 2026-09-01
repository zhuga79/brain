"""Remote `[~]` in a synced queue is a lock, not an invitation to take over.

`.locks/` is runtime-local and never synced. After a git pull the only evidence
that another node holds a task is a fresh in-progress row in `tasks/active.md`
with `node:` of a different identity. `brain-lock acquire` must refuse that
row for the duration of its TTL.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_core.clock import parse as parse_ts
from brain_core.taskfile import LOCK_TTL_DEFAULT
from brain_task_parser import find_block, parse_block

from .core import node_id


@dataclass(frozen=True)
class RemoteLock:
    task_id: str
    node: str
    started: str
    by: str
    ttl_s: int
    age_s: int

    def as_json(self) -> dict[str, Any]:
        return {
            "ok": False,
            "task_id": self.task_id,
            "node": self.node,
            "owner": self.by,
            "stale": False,
            "age_s": self.age_s,
            "ttl_s": self.ttl_s,
            "error": "remote_in_progress",
        }


def _int_ttl(value: object, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def remote_lock_conflict(
    active: Path,
    task_id: str,
    *,
    local_node: str,
    now: datetime | None = None,
    default_ttl: int = LOCK_TTL_DEFAULT,
) -> RemoteLock | None:
    """Return the remote holder if `task_id` is a fresh `[~]` on another node.

    No conflict when the file is missing, the task is absent/open, `node:` is
    empty (legacy single-user `[~]`), the node matches `local_node`, or
    `started:` is older than the row's TTL. Missing or unparseable `started:`
    is treated as fresh — we cannot prove the remote lock expired.
    """
    if not str(task_id or "").strip():
        return None
    try:
        text = active.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    block = find_block(text, task_id)
    if not block:
        return None
    parsed = parse_block(block)
    if not parsed or parsed.get("state") != "~":
        return None
    node = str(parsed.get("node") or "").strip()
    if not node or node == local_node:
        return None
    started = str(parsed.get("started") or "").strip()
    ttl_s = _int_ttl(parsed.get("ttl"), default_ttl)
    moment = now or datetime.now(timezone.utc)
    started_dt = parse_ts(started)
    if started_dt is None:
        age_s = 0
    else:
        age_s = max(0, int((moment - started_dt).total_seconds()))
        if age_s > ttl_s:
            return None
    return RemoteLock(
        task_id=task_id,
        node=node,
        started=started,
        by=str(parsed.get("by") or "").strip(),
        ttl_s=ttl_s,
        age_s=age_s,
    )


def cmd_check(args: argparse.Namespace) -> int:
    active = Path(args.active).expanduser()
    local = str(args.node or "").strip()
    if not local:
        local = node_id(active.parent.parent)
    hit = remote_lock_conflict(active, args.task, local_node=local)
    if hit is None:
        if args.json:
            print(json.dumps({"ok": True, "task_id": args.task}))
        return 0
    if args.json:
        print(json.dumps(hit.as_json(), ensure_ascii=False))
    else:
        owner = hit.by or "unknown"
        print(
            f"locked by: {owner} on node {hit.node} "
            f"(age {hit.age_s}s, ttl {hit.ttl_s}s)"
        )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="brain_federation.remote_lock")
    sub = parser.add_subparsers(dest="cmd")
    check = sub.add_parser("check", help="Refuse if active.md holds a fresh remote [~]")
    check.add_argument("--active", required=True, help="Path to tasks/active.md")
    check.add_argument("--task", required=True, help="Task id to inspect")
    check.add_argument("--node", default="", help="Local node id (default: node_id())")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=cmd_check)
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
