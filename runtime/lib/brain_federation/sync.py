"""Sync operations for brain_federation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from .git_ops import git_pull_rebase, git_push, is_git_repo
from .core import result, emit, exit_code, Finding, node_id
from .merger import merge_blocks
from .plan import utc_now
import brain_task_parser


def log_sync(brain: Path, repo: Path, status: str) -> None:
    """Append a node-attributed federation-sync audit row to wiki/log.md."""
    log_path = brain / "wiki" / "log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    node = node_id(brain)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"## [{utc_now()}] federation-sync | {repo} | node={node} | status={status}\n"
        )


def cmd_merge_tasks(args: argparse.Namespace) -> int:
    """CLI to merge two task files using a common ancestor."""
    base_path = Path(args.base).expanduser()
    local_path = Path(args.local).expanduser()
    remote_path = Path(args.remote).expanduser()
    
    base_text = base_path.read_text(encoding="utf-8")
    local_text = local_path.read_text(encoding="utf-8")
    remote_text = remote_path.read_text(encoding="utf-8")
    
    base_blocks = {p["id"]: p for p in [brain_task_parser.parse_block(b) for b in brain_task_parser.find_blocks(base_text)]}
    local_blocks = {p["id"]: p for p in [brain_task_parser.parse_block(b) for b in brain_task_parser.find_blocks(local_text)]}
    remote_blocks = {p["id"]: p for p in [brain_task_parser.parse_block(b) for b in brain_task_parser.find_blocks(remote_text)]}
    
    # We'll regenerate the file by iterating over IDs present in any of the files.
    # To maintain some order, we can use local IDs then new remote IDs.
    all_ids = list(local_blocks.keys())
    for tid in remote_blocks:
        if tid not in all_ids:
            all_ids.append(tid)
            
    merged_blocks_text = []
    for tid in all_ids:
        b = base_blocks.get(tid)
        l = local_blocks.get(tid)
        r = remote_blocks.get(tid)
        
        if l and r:
            if not b:
                # New in both! Treat local as base for a 2-way-like merge or just pick one.
                # Here we simulate 3-way with empty base if needed, but merger expects base.
                b = {"id": tid, "state": " ", "prio": "P2", "title": ""}
            merged_info = merge_blocks(b, l, r)
            merged_blocks_text.append(brain_task_parser.format_block(merged_info))
        elif l:
            merged_blocks_text.append(brain_task_parser.format_block(l))
        elif r:
            # If present in base and remote but NOT local, it was deleted in local.
            # For simplicity, if it was deleted in one side, we keep it if it changed in other side.
            if b and r == b:
                # Deleted in local, same in base/remote. Keep deleted.
                continue
            merged_blocks_text.append(brain_task_parser.format_block(r))

    output = "# Merged Tasks\n\n" + "\n\n".join(merged_blocks_text) + "\n"
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    else:
        print(output)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    repo = Path(args.repo or ".").resolve()
    if not is_git_repo(repo):
        print(f"Error: {repo} is not a git repository", file=sys.stderr)
        return 1

    brain = Path(args.brain).expanduser() if getattr(args, "brain", None) else repo
    findings: list[Finding] = []
    
    print(f"Syncing {repo}...")
    
    # 1. Pull --rebase
    res_pull = git_pull_rebase(repo)
    if res_pull.returncode != 0:
        print(f"Pull failed:\n{res_pull.stderr}", file=sys.stderr)
        findings.append(Finding("federation-sync-pull-failed", "block", str(repo), f"git pull --rebase failed: {res_pull.stderr}"))
        log_sync(brain, repo, "pull-failed")
        data = result("sync", repo, brain, findings)
        emit(data, args.json)
        return exit_code(findings)
    print("Pull/Rebase OK")

    # 2. Push
    res_push = git_push(repo)
    if res_push.returncode != 0:
        print(f"Push failed:\n{res_push.stderr}", file=sys.stderr)
        findings.append(Finding("federation-sync-push-failed", "block", str(repo), f"git push failed: {res_push.stderr}"))
        log_sync(brain, repo, "push-failed")
        data = result("sync", repo, brain, findings)
        emit(data, args.json)
        return exit_code(findings)
    print("Push OK")

    log_sync(brain, repo, "ok")
    data = result("sync", repo, brain, findings)
    data["status"] = "synced"
    emit(data, args.json)
    return 0
