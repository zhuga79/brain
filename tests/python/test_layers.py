"""t-2026-08-10-autocommit-scope: граница между слоем данных и системой."""

from pathlib import Path

import pytest

from brain_core.layers import (
    DATA_PATHS,
    SYSTEM_PATHS,
    agent_branch,
    is_system_path,
    system_paths_among,
)

REPO = Path(__file__).resolve().parent.parent.parent


@pytest.mark.parametrize("path", [
    "roles/lawyer.md", "doctrine/tax-boundaries.md", "runtime/bin/brain-task",
    "config/routing.json", "MEMORY.md", "tests/cases/01.sh", "pyproject.toml",
])
def test_system_paths(path):
    assert is_system_path(path)


@pytest.mark.parametrize("path", [
    "tasks/active.md", "wiki/index.md", "wiki/roles.md", "raw/source.md",
    "council/t-1/architect.md", "prd/plan.md",
])
def test_data_paths(path):
    assert not is_system_path(path)


def test_prefix_match_is_not_substring_match():
    """wiki/roles.md — страница знаний, а не роль: сравнение по префиксу пути."""
    assert not is_system_path("wiki/roles.md")
    assert not is_system_path("raw/runtime-notes.md")


def test_layers_do_not_overlap():
    for data in DATA_PATHS:
        assert not is_system_path(data), f"{data} числится и данными, и системой"


def test_system_paths_among_keeps_order_and_dedupes():
    got = system_paths_among(["tasks/a.md", "roles/x.md", "roles/x.md", "runtime/y"])
    assert got == ["roles/x.md", "runtime/y"]


def test_agent_branch_is_task_scoped():
    assert agent_branch("t-2026-08-10-x") == "agent/t-2026-08-10-x"


def test_agent_branch_sanitizes_input():
    """Идентификатор приходит из окружения — в имени ветки не должно быть мусора."""
    assert agent_branch("t-1;rm -rf /") == "agent/t-1-rm--rf--"
    assert agent_branch("") == "agent/unscoped"


def test_autocommit_stages_only_data_layer():
    text = (REPO / "runtime" / "bin" / "brain-common").read_text(encoding="utf-8")
    body = text.split("git_commit()", 1)[1].split("\n}", 1)[0]
    # Смотрим на строки с git add, а не на весь текст: в комментарии рядом
    # перечислено, что именно сюда больше не попадает, и это полезно.
    staged = [ln for ln in body.splitlines() if "git add" in ln]
    assert staged, "в git_commit не осталось git add"
    for system in ("roles/", "doctrine/", "teams/", "MEMORY.md"):
        assert not any(system in ln for ln in staged), f"автокоммит снова трогает {system}"


def test_mcp_git_commit_stages_only_data_layer():
    """MCP-копия git_commit() — тот же контракт, что и у shell-хелпера."""
    text = (REPO / "runtime" / "mcp" / "common.py").read_text(encoding="utf-8")
    body = text.split("def git_commit", 1)[1].split("\ndef ", 1)[0]
    for system in ('"roles/"', '"doctrine/"', '"teams/"', '"MEMORY.md"'):
        assert system not in body, f"MCP git_commit still stages {system}"
    for data in ('"tasks/"', '"wiki/"', '"council/"', '"raw/"', '"prd/"'):
        assert data in body or "DATA_PATHS" in body, (
            f"MCP git_commit dropped data path {data}"
        )


def test_guard_hook_exists_and_is_wired():
    guard = REPO / "runtime" / "hooks" / "pre-commit-system-guard"
    assert guard.is_file()
    installer = (REPO / "install-hooks.sh").read_text(encoding="utf-8")
    assert "pre-commit-system-guard" in installer
