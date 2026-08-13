"""Preflight checks for Brain vault federation."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from .core import (
    Finding,
    brain_path,
    emit,
    exit_code,
    parse_task_file,
    result,
)
from .checks import (
    check_council_synthesis_stale,
    check_gitignore,
    check_learning_status_conflict,
    check_lock_conflicts,
    check_optional_secret_scanner,
    check_possible_secrets,
    check_provider_matrix,
    check_raw_rewrites,
    check_runtime_paths,
    check_wiki_curation,
)
from .git_ops import (
    git_name_status,
    git_paths,
    is_git_repo,
)


def parse_task_file_optional(
    path: Path,
    source: str,
    flag_in_progress: bool = True,
) -> tuple[list[dict[str, Any]], list[Finding]]:
    """Parse a task file if it exists; return empty lists if not."""
    if not path.exists():
        return [], []
    return parse_task_file(path, source, flag_in_progress=flag_in_progress)


def collect_preflight(
    repo: Path, brain: Path
) -> tuple[dict[str, Any], list[Finding], set[str]]:
    """Run all preflight checks against repo and return (data, findings, changed_paths)."""
    if not repo.exists() or not repo.is_dir():
        raise FileNotFoundError(str(repo))

    findings: list[Finding] = []
    changed_paths: set[str] = set()
    name_status: list[tuple[str, str]] = []
    if is_git_repo(repo):
        changed_paths = git_paths(repo)
        name_status = git_name_status(repo)
    else:
        findings.append(
            Finding(
                "outside-git-repo",
                "warn",
                str(repo),
                "preflight ran without git metadata and used filesystem checks only",
                "run inside a git working tree for full conflict detection",
            )
        )

    findings.extend(check_runtime_paths(repo, changed_paths))
    findings.extend(check_raw_rewrites(name_status))
    findings.extend(check_wiki_curation(repo, changed_paths))
    findings.extend(check_provider_matrix(repo, changed_paths))
    if is_git_repo(repo):
        findings.extend(check_possible_secrets(repo))
    findings.extend(check_optional_secret_scanner(repo))
    if is_git_repo(repo):
        findings.extend(check_gitignore(repo))
    findings.extend(check_learning_status_conflict(repo))
    findings.extend(check_council_synthesis_stale(repo))
    findings.extend(check_lock_conflicts(repo, changed_paths))

    data = result("preflight", repo, brain, findings)
    return data, findings, changed_paths


def cmd_preflight(args: argparse.Namespace) -> int:
    """Handle the `preflight` subcommand."""
    repo = Path(args.repo or os.getcwd()).expanduser()
    brain = brain_path(args.brain)
    try:
        data, findings, _changed_paths = collect_preflight(repo, brain)
    except FileNotFoundError as exc:
        print(f"brain-federation preflight: unreadable repo path: {exc}", file=sys.stderr)
        return 2
    emit(data, args.json)
    return exit_code(findings)
