"""sync-cycle: синхронизация Brain с LAN-репозиторием, безопасная по составу.

Цикл синхронизирует только durable-состояние под git. Runtime — локи, собранные
индексы, кеши провайдеров — обязан остаться локальным, и попытка его синхронизации
блокирует прогон, а не «решается» тихо.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from brain_federation.core import Finding, RUNTIME_PATHS
from brain_federation.git_ops import is_git_repo, path_matches

from . import runner, systemd

NAME = "brain-sync-cycle"
DEFAULT_UNIT_NAME = "brain-sync"
DEFAULT_INTERVAL = "5min"
JOURNAL_PATH = "wiki/log.md"


def git_run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], check=False, capture_output=True, text=True)


def command_run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, check=False, capture_output=True, text=True, timeout=timeout
    )


def split_status_path(line: str) -> str:
    path = line[3:].strip()
    if " -> " in path:
        return path.split(" -> ", 1)[1]
    return path.strip('"')


def status_paths(repo: Path, *, include_untracked: bool) -> set[str]:
    flag = "--untracked-files=all" if include_untracked else "--untracked-files=no"
    res = git_run(repo, "status", "--porcelain", flag)
    if res.returncode != 0:
        return set()
    return {split_status_path(line) for line in res.stdout.splitlines() if line.strip()}


def matches_runtime(path: str) -> bool:
    return any(path_matches(path, pattern) for pattern in RUNTIME_PATHS)


def _journal_is_append_only(repo: Path) -> bool:
    """The working-tree journal must extend HEAD's, never shrink it.

    wiki/log.md is append-only. A working copy that is shorter than, or does
    not start with, the committed one is corruption (a stale sync helper
    truncated it, a bad merge emptied it — t-2026-09-02-wiki-log-md), and
    committing that would bake the loss into history. Refuse instead.
    """
    head = git_run(repo, "show", f"HEAD:{JOURNAL_PATH}")
    if head.returncode != 0:
        return True  # not tracked yet — nothing to lose
    committed = head.stdout.rstrip("\n")
    try:
        working = (repo / JOURNAL_PATH).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return len(working) >= len(committed) and working.startswith(committed)


def autocommit_journal(repo: Path) -> bool:
    """Автокоммит append-only журнала перед preflight.

    Пробы и циклы дописывают wiki/log.md без коммита, из-за чего каждый
    автоматический синк блокировался dirty-worktree. Журнал коммитим только
    когда он — единственная незакоммиченная durable-правка; любые другие
    изменения по-прежнему требуют ручного коммита. Усечённый журнал не
    коммитим — это порча, а не дозапись.
    """
    dirty_durable = sorted(path for path in status_paths(repo, include_untracked=False) if not matches_runtime(path))
    if dirty_durable != [JOURNAL_PATH]:
        return False
    if not _journal_is_append_only(repo):
        return False
    if git_run(repo, "add", "--", JOURNAL_PATH).returncode != 0:
        return False
    commit = git_run(
        repo, "commit", "--no-verify", "-m", "chore: автозаписи журнала (brain-sync)", "--", JOURNAL_PATH
    )
    return commit.returncode == 0


def commit_journal_after_sync(repo: Path, already_committed: bool) -> bool:
    """Коммитим node-атрибутированные audit-строки, добавленные
    `brain-federation sync` в wiki/log.md после pull/push.

    Без этого следующий же прогон цикла блокировался dirty-worktree: журнал
    остаётся единственной незакоммиченной durable-правкой, и её нужно забрать
    в коммит так же, как до-синковые автозаписи проб и циклов.
    """
    return autocommit_journal(repo) or already_committed


def collect_findings(repo: Path) -> list[Finding]:
    if not repo.exists() or not repo.is_dir():
        return [Finding(
            "repo-not-found", "block", str(repo),
            "repository path does not exist",
            "pass --repo or set BRAIN_PATH to the Brain checkout",
        )]
    if not is_git_repo(repo):
        return [Finding(
            "outside-git-repo", "block", str(repo),
            "brain-sync-cycle requires a git working tree",
            "initialize Brain as git or clone it from the LAN remote",
        )]

    findings: list[Finding] = []
    runtime_reported: set[str] = set()
    for path in sorted(status_paths(repo, include_untracked=True)):
        if not matches_runtime(path):
            continue
        root = next((pattern.rstrip("/") for pattern in RUNTIME_PATHS if path_matches(path, pattern)), path)
        if root in runtime_reported:
            continue
        runtime_reported.add(root)
        findings.append(Finding(
            "runtime-file-included", "block", root,
            "runtime-local/generated Brain file must not be synced",
            "remove it from git and keep it ignored",
        ))

    dirty_durable = sorted(path for path in status_paths(repo, include_untracked=False) if not matches_runtime(path))
    for path in dirty_durable:
        findings.append(Finding(
            "dirty-worktree", "block", path,
            "tracked durable Brain file has uncommitted changes",
            "commit or resolve local changes before automatic sync",
        ))
    if JOURNAL_PATH in dirty_durable and not _journal_is_append_only(repo):
        findings.append(Finding(
            "journal-corrupted", "block", JOURNAL_PATH,
            "wiki/log.md working copy is shorter than the committed one — it was truncated",
            "restore it from git (git checkout wiki/log.md or the last full commit) before syncing",
        ))
    return findings


def result(mode: str, repo: Path, brain: Path, findings: list[Finding], **extra: Any) -> dict[str, Any]:
    summary = {"block": 0, "review": 0, "warn": 0, "info": 0}
    for finding in findings:
        summary[finding.severity] = summary.get(finding.severity, 0) + 1
    data: dict[str, Any] = {
        "ok": summary.get("block", 0) == 0,
        "mode": mode,
        "repo": str(repo),
        "brain": str(brain),
        "summary": summary,
        "findings": [finding.as_json() for finding in findings],
    }
    data.update(extra)
    return data


def emit(data: dict[str, Any], json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
        return
    status = data.get("status") or ("ok" if data.get("ok") else "blocked")
    print(f"brain-sync-cycle {data.get('mode')}: {status}")
    for finding in data.get("findings", []):
        print(f"  [{finding['severity']}] {finding['code']} {finding['path']}: {finding['message']}")
        if finding.get("hint"):
            print(f"      hint: {finding['hint']}")


def repo_path(args: argparse.Namespace, brain: Path) -> Path:
    return Path(getattr(args, "repo", None) or brain).expanduser().resolve()


def dry_run(args: argparse.Namespace) -> int:
    brain = runner.resolve_brain(args)
    repo = repo_path(args, brain)
    findings = collect_findings(repo)
    blocked = any(finding.severity == "block" for finding in findings)
    emit(result("dry-run", repo, brain, findings, status="blocked" if blocked else "ready",
                would_sync=not blocked), args.json)
    return 1 if blocked else 0


def apply_sync(args: argparse.Namespace) -> int:
    brain = runner.resolve_brain(args)
    repo = repo_path(args, brain)
    journal_committed = autocommit_journal(repo)
    findings = collect_findings(repo)
    if any(finding.severity == "block" for finding in findings):
        emit(result("apply", repo, brain, findings, status="blocked", synced=False,
                    journal_committed=journal_committed), args.json)
        return 1

    try:
        sync_proc = command_run(
            ["brain-federation", "sync", "--repo", str(repo), "--brain", str(brain), "--json"],
            cwd=repo, timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        journal_committed = commit_journal_after_sync(repo, journal_committed)
        findings.append(Finding(
            "sync-timeout", "block", str(repo),
            f"brain-federation sync exceeded {args.timeout}s",
            "check LAN connectivity and remote git availability",
        ))
        emit(result("apply", repo, brain, findings, status="failed", synced=False,
                    journal_committed=journal_committed), args.json)
        return 1

    if sync_proc.returncode != 0:
        journal_committed = commit_journal_after_sync(repo, journal_committed)
        findings.append(Finding(
            "sync-failed", "block", str(repo), "brain-federation sync failed",
            (sync_proc.stderr or sync_proc.stdout).strip(),
        ))
        emit(result("apply", repo, brain, findings, status="failed", synced=False,
                    journal_committed=journal_committed,
                    sync_stdout=sync_proc.stdout.strip(),
                    sync_stderr=sync_proc.stderr.strip()), args.json)
        return 1

    journal_committed = commit_journal_after_sync(repo, journal_committed)

    rebuild_data: dict[str, Any] = {}
    if args.rebuild_index:
        rebuild_proc = command_run(["brain-index", "rebuild"], cwd=brain, timeout=300)
        rebuild_data = {
            "index_rebuild_exit_code": rebuild_proc.returncode,
            "index_rebuild_stdout": rebuild_proc.stdout.strip(),
            "index_rebuild_stderr": rebuild_proc.stderr.strip(),
        }
        if rebuild_proc.returncode != 0:
            findings.append(Finding(
                "index-rebuild-failed", "warn", str(brain / ".brain" / "index"),
                "sync succeeded but index rebuild failed", rebuild_proc.stderr.strip(),
            ))

    emit(result("apply", repo, brain, findings, status="synced", synced=True,
                journal_committed=journal_committed,
                sync_stdout=sync_proc.stdout.strip(),
                sync_stderr=sync_proc.stderr.strip(), **rebuild_data), args.json)
    return 0


def run(args: argparse.Namespace) -> int:
    return apply_sync(args) if args.apply else dry_run(args)


def unit(args: argparse.Namespace) -> systemd.UnitSpec:
    brain = runner.resolve_brain(args)
    repo = repo_path(args, brain)
    exec_args = ["--brain", str(brain), "--repo", str(repo), "--apply", "--json"]
    if not args.rebuild_index:
        exec_args.append("--no-rebuild-index")
    return systemd.UnitSpec(
        name=args.unit_name,
        service_description="Synchronize Brain durable state with LAN git remote",
        timer_description=f"Run Brain LAN synchronization every {args.interval}",
        command=systemd.resolve_command(NAME),
        exec_args=exec_args,
        timer_options=[("OnBootSec", "2min"), ("OnUnitActiveSec", args.interval), ("Persistent", "true")],
        unit_options=[("After", "network-online.target"), ("Wants", "network-online.target")],
        working_dir=repo,
        environment=runner.service_environment(brain),
    )


def repo_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=None, help="Путь к git-репозиторию (по умолчанию — корень Brain).")
    parser.add_argument("--rebuild-index", dest="rebuild_index", action="store_true", default=True)
    parser.add_argument("--no-rebuild-index", dest="rebuild_index", action="store_false")


def run_args(parser: argparse.ArgumentParser) -> None:
    repo_args(parser)
    parser.add_argument("--timeout", type=int, default=300, help="Таймаут синхронизации в секундах.")


def install_args(parser: argparse.ArgumentParser) -> None:
    repo_args(parser)
    parser.add_argument("--unit-name", default=DEFAULT_UNIT_NAME, help="Базовое имя юнита.")
    parser.add_argument("--interval", default=DEFAULT_INTERVAL, help="Интервал таймера, например 5min или 1h.")


SPEC = runner.CycleSpec(
    name=NAME,
    description="Install and run a LAN-safe Brain git synchronizer.",
    install_description="Write brain-sync user systemd service/timer.",
    run=run,
    unit=unit,
    mode_required=True,
    run_args=run_args,
    install_args=install_args,
)
