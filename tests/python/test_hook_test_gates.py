"""t-2026-08-31-split-git-hook-test-gates-fast: policy on commit, suite on push.

Harness repos only. Does not touch the live checkout or its index.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
INSTALLER = REPO / "install-hooks.sh"
RUN_SH = REPO / "tests" / "run.sh"
DROP_GIT_ENV = REPO / "tests" / "lib" / "drop-git-env.sh"


def _env(**extra: str) -> dict[str, str]:
    """Allowlist for harness git/hook subprocesses. No GIT_*, no BRAIN_*."""
    keep: dict[str, str] = {}
    for key in (
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "TMPDIR",
        "TZ",
        "SHELL",
    ):
        val = os.environ.get(key)
        if val:
            keep[key] = val
    keep.setdefault("LANG", "C.UTF-8")
    keep.update(extra)
    return keep


def _run(
    cwd: Path,
    args: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        env=env if env is not None else _env(),
        input=input_text,
    )


def _git(cwd: Path, *args: str, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return _run(cwd, ["git", *args], check=check, env=env)


def _harness_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "gates@example.invalid")
    _git(repo, "config", "user.name", "gates")
    (repo / "README").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-qm", "base")
    return repo


def _install_hooks(repo: Path) -> subprocess.CompletedProcess[str]:
    return _run(repo, ["bash", str(INSTALLER)])


def _hook(repo: Path, name: str) -> Path:
    hooks = _git(repo, "rev-parse", "--git-path", "hooks").stdout.strip()
    path = Path(hooks)
    if not path.is_absolute():
        path = repo / path
    return path / name


@pytest.fixture
def harness(tmp_path: Path) -> Path:
    repo = _harness_repo(tmp_path)
    _install_hooks(repo)
    return repo


def test_installer_resolves_hooks_dir_at_runtime():
    text = INSTALLER.read_text(encoding="utf-8")
    assert "git rev-parse --git-path hooks" in text
    assert "git rev-parse --show-toplevel" in text
    assert 'PROJECT_ROOT="${PROJECT_ROOT}"' not in text
    assert "unset GIT_INDEX_FILE" not in text
    assert "env -i" in text
    assert "index.lock" not in text


def test_run_sh_drops_git_vars_by_prefix_not_denylist():
    text = RUN_SH.read_text(encoding="utf-8")
    assert "drop-git-env" in text or "GIT_*)" in text
    assert "unset GIT_INDEX_FILE" not in text
    assert "unset GIT_DIR" not in text


def test_drop_git_env_removes_known_and_unknown_keys():
    """Parent injects GIT_INDEX_FILE, GIT_DIR, GIT_ZZZ_*; after drop, zero GIT_*."""
    assert DROP_GIT_ENV.is_file(), "tests/lib/drop-git-env.sh must exist"
    script = f"""
set -euo pipefail
export GIT_INDEX_FILE=/tmp/idx
export GIT_DIR=/tmp/git
export GIT_ZZZ_PROBE=leak
export KEEP_ME=1
. "{DROP_GIT_ENV}"
python3 -c "import os; git=sorted(k for k in os.environ if k.startswith('GIT_')); print('KEYS=' + ','.join(git)); print('KEEP=' + os.environ.get('KEEP_ME',''))"
"""
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "KEEP=1" in done.stdout
    keys_line = [ln for ln in done.stdout.splitlines() if ln.startswith("KEYS=")]
    assert keys_line, done.stdout
    assert keys_line[0] == "KEYS=", f"GIT_* survived drop: {keys_line[0]}"


def test_installed_precommit_is_policy_only(harness: Path):
    pre = _hook(harness, "pre-commit")
    push = _hook(harness, "pre-push")
    assert pre.is_file() and os.access(pre, os.X_OK)
    assert push.is_file() and os.access(push, os.X_OK)
    pre_text = pre.read_text(encoding="utf-8")
    push_text = push.read_text(encoding="utf-8")
    assert "tests/run.sh" not in pre_text
    assert "pytest" not in pre_text
    assert "git rev-parse --show-toplevel" in pre_text
    assert "pre-commit-write-path" in pre_text
    assert "pre-commit-system-guard" in pre_text
    assert "bash -n" in pre_text
    assert "brain-uiux-lint" in pre_text
    assert "brain-guard" in pre_text
    assert "--added-only" in pre_text
    assert "rm " not in pre_text or "index.lock" not in pre_text
    assert str(REPO) not in pre_text
    assert "tests/run.sh" in push_text
    assert "pytest" in push_text
    assert "env -i" in push_text
    assert "unset GIT_INDEX_FILE" not in push_text
    assert "git rev-parse --show-toplevel" in push_text
    assert str(REPO) not in push_text
    assert "rm " not in push_text or "index.lock" not in push_text


def test_suite_process_sees_no_git_star(harness: Path, tmp_path: Path):
    """Inject GIT_INDEX_FILE, GIT_DIR and GIT_ZZZ_*; suite process has zero GIT_*."""
    tests = harness / "tests"
    tests.mkdir()
    dump = harness / "git-env-leaked.txt"
    (tests / "run.sh").write_text(
        "#!/usr/bin/env bash\n"
        "python3 - <<'PY'\n"
        "import os\n"
        "from pathlib import Path\n"
        "keys = sorted(k for k in os.environ if k.startswith('GIT_'))\n"
        "Path('git-env-leaked.txt').write_text('\\n'.join(keys))\n"
        "PY\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (tests / "run.sh").chmod(stat.S_IRWXU)
    env = _env(
        GIT_INDEX_FILE=str(harness / ".git" / "index"),
        GIT_DIR=str(harness / ".git"),
        GIT_ZZZ_PROBE="leak-me",
    )
    done = _run(
        harness,
        [str(_hook(harness, "pre-push"))],
        check=False,
        env=env,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert dump.is_file(), done.stdout + done.stderr
    leaked = [ln for ln in dump.read_text(encoding="utf-8").splitlines() if ln]
    assert leaked == [], f"GIT_* leaked into suite process: {leaked}"


def test_commit_from_checkout_and_worktree(harness: Path, tmp_path: Path):
    (harness / "n").write_text("one\n", encoding="utf-8")
    _git(harness, "add", "n")
    first = _git(harness, "commit", "-m", "from checkout")
    combined = first.stdout + first.stderr
    assert first.returncode == 0
    assert "[pre-commit]" in combined

    wt = tmp_path / "wt"
    _git(harness, "worktree", "add", str(wt))
    (wt / "n").write_text("two\n", encoding="utf-8")
    _git(wt, "add", "n")
    second = _git(wt, "commit", "-m", "from worktree")
    combined = second.stdout + second.stderr
    assert second.returncode == 0
    assert "[pre-commit]" in combined
    assert not (wt / ".git").is_dir()


def test_sigint_during_fast_precommit_does_not_leave_index_lock(harness: Path):
    pre = _hook(harness, "pre-commit")
    original = pre.read_text(encoding="utf-8")
    assert "index.lock" not in original
    pre.write_text("#!/usr/bin/env bash\nsleep 5\n" + original, encoding="utf-8")
    pre.chmod(stat.S_IRWXU)
    (harness / "n").write_text("interrupt\n", encoding="utf-8")
    _git(harness, "add", "n")
    timeout = shutil.which("timeout")
    assert timeout, "coreutils timeout is required for the SIGINT gate test"
    interrupted = _run(
        harness,
        [timeout, "--preserve-status", "--signal=INT", "1s", "git", "commit", "-m", "interrupted"],
        check=False,
    )
    # Restore the fast hook. The next commit must not be 128 because of a leftover lock.
    pre.write_text(original, encoding="utf-8")
    pre.chmod(stat.S_IRWXU)
    lock = harness / ".git" / "index.lock"
    assert interrupted.returncode != 0
    (harness / "n").write_text("after\n", encoding="utf-8")
    added = _git(harness, "add", "n", check=False)
    assert added.returncode != 128, added.stderr
    assert not lock.exists(), "index.lock survived SIGINT; next commit would be 128"
    after = _git(harness, "commit", "-m", "after interrupt", check=False)
    assert after.returncode != 128, after.stderr
    assert after.returncode == 0, after.stdout + after.stderr
    assert "[pre-commit]" in (after.stdout + after.stderr)
