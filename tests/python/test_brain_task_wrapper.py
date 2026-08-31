"""t-2026-08-21-brain-task-add / t-2026-08-14-task-add-option-passthrough.

Обёртка runtime/bin/brain-task пишет журнал и коммитит по stdout python-слоя,
не проверяя ни код возврата, ни форму id. Воспроизведение: `brain-task add --help`
печатает справку argparse в stdout, задачи нет, а в wiki/log.md ложится
многострочный `task-add | usage: ...` и создаётся коммит с той же справкой.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BIN = REPO / "runtime" / "bin"
BRAIN_TASK = BIN / "brain-task"

TASK_ID_RE = re.compile(r"^t-[0-9]{4}-[0-9]{2}-[0-9]{2}-[A-Za-z0-9_.-]+$")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _brain(tmp_path: Path) -> Path:
    """Изолированное дерево данных с git, как у живого BRAIN_PATH."""
    brain = tmp_path / "brain"
    (brain / "tasks").mkdir(parents=True)
    (brain / "wiki").mkdir()
    (brain / "tasks" / "active.md").write_text("# Active Tasks\n", encoding="utf-8")
    (brain / "tasks" / "done.md").write_text("# Done\n", encoding="utf-8")
    (brain / "wiki" / "log.md").write_text("# Log\n", encoding="utf-8")
    _git(brain, "init", "-q", "-b", "master")
    _git(brain, "config", "user.email", "case@example.invalid")
    _git(brain, "config", "user.name", "case")
    _git(brain, "add", "tasks", "wiki")
    _git(brain, "commit", "-qm", "base")
    return brain


def _env(brain: Path, home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["BRAIN_PATH"] = str(brain)
    env["BRAIN_SYSTEM_PATH"] = str(REPO)
    env["BRAIN_SKIP_OPERATOR_ENV"] = "1"
    env["PYTHONPATH"] = str(REPO / "runtime" / "lib")
    env["PATH"] = f"{BIN}{os.pathsep}{env.get('PATH', '')}"
    return env


def _run(brain: Path, home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(BRAIN_TASK), *args],
        env=_env(brain, home),
        capture_output=True,
        text=True,
    )


def _log_text(brain: Path) -> str:
    return (brain / "wiki" / "log.md").read_text(encoding="utf-8")


def _commits(brain: Path) -> list[str]:
    done = subprocess.run(
        ["git", "log", "--format=%s"], cwd=brain, capture_output=True, text=True, check=True,
    )
    return [line for line in done.stdout.splitlines() if line]


def _case_block(source: str, name: str) -> str:
    """Тело `case` ветки brain-task до следующего одноуровневого паттерна."""
    match = re.search(rf"^  {re.escape(name)}\)\n", source, re.M)
    assert match, f"ветка {name} не найдена"
    start = match.end()
    nxt = re.search(r"^  [a-zA-Z0-9_|-]+\)\n", source[start:], re.M)
    return source[start: start + nxt.start()] if nxt else source[start:]


# ── t-2026-08-21-brain-task-add: журнал только после подтверждённой мутации ──


@pytest.mark.integration
def test_add_help_does_not_journal_or_commit(tmp_path):
    """RED на текущем поведении: add --help пишет usage в журнал и коммитит его.

    argparse печатает справку в stdout и выходит с нулём. Обёртка принимает
    этот текст за id, зовёт log_op и git_commit. Журнал — доказательная база:
    запись о несостоявшейся мутации хуже отсутствия записи.
    """
    home = tmp_path / "home"
    home.mkdir()
    brain = _brain(tmp_path)
    log_before = _log_text(brain)
    commits_before = _commits(brain)
    active_before = (brain / "tasks" / "active.md").read_text(encoding="utf-8")

    result = _run(brain, home, "add", "--help")

    log_after = _log_text(brain)
    assert "task-add" not in log_after, log_after
    assert "usage:" not in log_after
    assert "brain_app.queue" not in log_after
    assert log_after == log_before
    assert (brain / "tasks" / "active.md").read_text(encoding="utf-8") == active_before
    assert _commits(brain) == commits_before
    assert not any("usage:" in subject for subject in _commits(brain))
    # Справка может печататься, но мутации нет. Ненулевой код тоже допустим:
    # python-слой с --help выходит 0, обёртка обязана отказать без журнала.
    assert result.returncode != 0 or "usage:" in (result.stdout + result.stderr)


@pytest.mark.integration
def test_add_success_journals_only_a_valid_id(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    brain = _brain(tmp_path)

    result = _run(brain, home, "add", "Wrapper mutation gate", "--role", "developer")
    assert result.returncode == 0, result.stderr
    match = re.search(r"added: (t-[A-Za-z0-9_.-]+)", result.stdout)
    assert match, result.stdout
    task_id = match.group(1)
    assert TASK_ID_RE.match(task_id)
    log_after = _log_text(brain)
    assert f"task-add | {task_id} |" in log_after
    assert "usage:" not in log_after
    assert any(subject == f"task-add: {task_id}" for subject in _commits(brain))
    assert task_id in (brain / "tasks" / "active.md").read_text(encoding="utf-8")


@pytest.mark.integration
@pytest.mark.parametrize(
    ("args", "forbidden_op"),
    [
        (("take", "t-missing-xyz", "--as", "agent-1"), "task-start"),
        (("release", "t-missing-xyz", "--as", "agent-1"), "task-release"),
        (("complete", "t-missing-xyz", "--as", "agent-1", "--model", "grok-4.6"), "task-done"),
        (("block", "t-missing-xyz", "need-info", "--as", "agent-1"), "task-block"),
    ],
)
def test_failed_mutation_commands_do_not_journal(tmp_path, args, forbidden_op):
    """Инвариант для всех ветвей, которые зовут log_op/git_commit, не только add."""
    home = tmp_path / "home"
    home.mkdir()
    brain = _brain(tmp_path)
    log_before = _log_text(brain)
    commits_before = _commits(brain)

    result = _run(brain, home, *args)
    assert result.returncode != 0, result.stdout + result.stderr
    log_after = _log_text(brain)
    assert forbidden_op not in log_after
    assert log_after == log_before
    assert _commits(brain) == commits_before


@pytest.mark.integration
def test_reconcile_fix_does_not_journal_when_python_layer_fails(tmp_path):
    """reconcile --fix ловит rc python-слоя, но журнал писал безусловно."""
    home = tmp_path / "home"
    home.mkdir()
    brain = _brain(tmp_path)
    active = brain / "tasks" / "active.md"
    active.chmod(0o000)
    log_before = _log_text(brain)
    commits_before = _commits(brain)
    try:
        result = _run(brain, home, "reconcile", "--fix")
    finally:
        active.chmod(0o644)

    assert result.returncode != 0, result.stdout + result.stderr
    log_after = _log_text(brain)
    assert "task-reconcile" not in log_after
    assert log_after == log_before
    assert _commits(brain) == commits_before


def test_add_branch_refuses_unvalidated_python_stdout():
    """Структурный RED: ветка add журналирует stdout без _validate_id и без rc."""
    source = BRAIN_TASK.read_text(encoding="utf-8")
    add_block = _case_block(source, "add")
    assert "log_op" in add_block
    assert "git_commit" in add_block
    assert "validate_id" in add_block, "add должен проверять форму id до журнала"
    assert re.search(r"\brc\b", add_block), "add должен смотреть код возврата python-слоя"


def test_reconcile_branch_journals_only_on_zero_python_exit():
    source = BRAIN_TASK.read_text(encoding="utf-8")
    rec_block = _case_block(source, "reconcile")
    assert "log_op" in rec_block
    assert re.search(r'\[ "\$rc" -eq 0 \]', rec_block), "reconcile --fix журналирует только при rc=0"


def test_every_journal_branch_gates_log_op():
    """Каждая ветка с log_op/git_commit подтверждает мутацию до записи."""
    source = BRAIN_TASK.read_text(encoding="utf-8")
    for name in ("add", "take", "release", "complete", "block", "reconcile"):
        block = _case_block(source, name)
        assert "log_op" in block, name
        assert "git_commit" in block, name
        if name == "add":
            assert "validate_id" in block
            assert re.search(r"\brc\b", block)
        elif name == "reconcile":
            assert re.search(r'\[ "\$rc" -eq 0 \]', block)
        else:
            assert "|| exit" in block or "if !" in block, name
