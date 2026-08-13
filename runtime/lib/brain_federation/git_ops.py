"""Git operations for brain_federation."""
from __future__ import annotations

import subprocess
from pathlib import Path


def git_run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def is_git_repo(repo: Path) -> bool:
    res = git_run(repo, "rev-parse", "--is-inside-work-tree")
    return res.returncode == 0 and res.stdout.strip() == "true"


def git_paths(repo: Path) -> set[str]:
    paths: set[str] = set()
    status = git_run(repo, "status", "--porcelain")
    for line in status.stdout.splitlines():
        if not line:
            continue
        path = line[3:].strip()
        if " -> " in path:
            old_path, new_path = path.split(" -> ", 1)
            paths.add(old_path)
            paths.add(new_path)
        elif path:
            paths.add(path)
    diff = git_run(repo, "diff", "--name-only", "HEAD")
    for line in diff.stdout.splitlines():
        if line.strip():
            paths.add(line.strip())
    return paths


def git_name_status(repo: Path) -> list[tuple[str, str]]:
    res = git_run(repo, "diff", "--name-status", "HEAD")
    entries: list[tuple[str, str]] = []
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            entries.append((parts[0], parts[-1]))
    return entries


def git_show(repo: Path, path: str) -> str | None:
    res = git_run(repo, "show", f"HEAD:{path}")
    if res.returncode != 0:
        return None
    return res.stdout


def git_head(repo: Path) -> str:
    if not is_git_repo(repo):
        return ""
    res = git_run(repo, "rev-parse", "HEAD")
    return res.stdout.strip() if res.returncode == 0 else ""


def git_pull_rebase(repo: Path) -> subprocess.CompletedProcess[str]:
    return git_run(repo, "pull", "--rebase")


def git_push(repo: Path) -> subprocess.CompletedProcess[str]:
    return git_run(repo, "push")


def frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip().lower()] = value.strip().strip("'\"").lower()
    return data


def path_matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return path == pattern[:-1] or path.startswith(pattern)
    return path == pattern
