"""t-2026-08-14-single-write-path: system edits belong in the public checkout."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_core.layers import (
    INSTALLER_SHADOW_FILES,
    WRITE_PATH_PREFIXES,
    installer_shadow_reason,
    installer_shadows_in,
    is_data_repo_write,
    is_write_path,
    same_tree,
    write_path_among,
    write_path_violations,
)

REPO = Path(__file__).resolve().parent.parent.parent


@pytest.mark.parametrize("path", [
    "runtime/bin/brain-ops",
    "roles/developer.md",
    "tests/cases/97-single-write-path.sh",
    "spec/guide.md",
    "docs/decisions/decision-public-source-of-truth.md",
    "teams/code-contribution.md",
    "doctrine/tax-boundaries.md",
    "skills/uiux/core/ui-critique.md",
    "config/routing.json",
])
def test_write_path_prefixes_cover_system_dirs(path):
    assert is_write_path(path)


@pytest.mark.parametrize("path", [
    "wiki/index.md",
    "wiki/roles.md",
    "tasks/active.md",
    "raw/source.md",
    "council/t-1/architect.md",
    "prd/plan.md",
    "handoff/note.md",
    "MEMORY.md",
    None,
    "",
    "   ",
])
def test_data_and_empty_paths_are_not_write_paths(path):
    assert not is_write_path(path)


def test_write_path_is_prefix_not_substring():
    assert not is_write_path("wiki/runtime-notes.md")
    assert not is_write_path("raw/roles-draft.md")
    assert not is_write_path("handoff/tests-log.md")


def test_write_path_among_keeps_order_dedupes_and_skips_empty():
    got = write_path_among([
        "",
        None,  # type: ignore[list-item]
        "wiki/a.md",
        "runtime/x",
        "runtime/x",
        "spec/y.md",
        "   ",
    ])
    assert got == ["runtime/x", "spec/y.md"]


def test_write_path_among_rejects_invalid_types():
    assert write_path_among([1, object(), [], {"a": 1}]) == []  # type: ignore[list-item]


def test_same_tree_resolves_symlinks(tmp_path):
    real = tmp_path / "files"
    real.mkdir()
    link = tmp_path / "brain"
    link.symlink_to(real)
    assert same_tree(link, real)
    assert same_tree(str(link), str(real / "."))
    assert not same_tree(link, tmp_path / "other")
    assert not same_tree(None, real)
    assert not same_tree(real, "")


def test_is_data_repo_write_only_when_roots_split(tmp_path):
    data = tmp_path / "data"
    system = tmp_path / "system"
    other = tmp_path / "other"
    data.mkdir()
    system.mkdir()
    other.mkdir()
    assert is_data_repo_write(repo=data, data=data, system=system)
    assert not is_data_repo_write(repo=system, data=data, system=system)
    assert not is_data_repo_write(repo=other, data=data, system=system)
    assert not is_data_repo_write(repo=data, data=data, system=data)
    assert not is_data_repo_write(repo=None, data=data, system=system)
    assert not is_data_repo_write(repo=data, data=None, system=system)
    assert not is_data_repo_write(repo=data, data=data, system=None)


def test_violations_in_data_repo_only_for_system_paths(tmp_path):
    data = tmp_path / "data"
    system = tmp_path / "system"
    data.mkdir()
    system.mkdir()
    staged = ["wiki/log.md", "runtime/bin/brain-ops", "roles/developer.md"]
    assert write_path_violations(
        staged, repo=data, data=data, system=system
    ) == ["runtime/bin/brain-ops", "roles/developer.md"]
    assert write_path_violations(
        ["wiki/log.md"], repo=data, data=data, system=system
    ) == []
    assert write_path_violations(
        staged, repo=system, data=data, system=system
    ) == []
    assert write_path_violations(
        staged, repo=data, data=data, system=data
    ) == []
    assert write_path_violations(None, repo=data, data=data, system=system) == []
    assert write_path_violations([], repo=data, data=data, system=system) == []


def test_symlink_data_root_still_blocks(tmp_path):
    real = tmp_path / "files"
    real.mkdir()
    link = tmp_path / "brain"
    link.symlink_to(real)
    system = tmp_path / "public"
    system.mkdir()
    assert write_path_violations(
        ["runtime/hooks/pre-commit-write-path"],
        repo=real,
        data=link,
        system=system,
    ) == ["runtime/hooks/pre-commit-write-path"]


def test_hook_exists_and_is_wired():
    hook = REPO / "runtime" / "hooks" / "pre-commit-write-path"
    assert hook.is_file()
    text = hook.read_text(encoding="utf-8")
    assert "write_path_violations" in text
    installer = (REPO / "install-hooks.sh").read_text(encoding="utf-8")
    assert "pre-commit-write-path" in installer
    setup = (REPO / "setup-brain-v2.sh").read_text(encoding="utf-8")
    assert "pre-commit-write-path" in setup


def test_docs_name_public_checkout_branch():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    contrib = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
    joined = readme + "\n" + contrib
    assert "ветк" in joined
    assert "BRAIN_SYSTEM_PATH" in joined
    assert "brain-ops update" in joined
    assert "tests/run.sh" in joined


def test_write_path_prefixes_are_explicit():
    for prefix in ("runtime/", "roles/", "tests/", "spec/"):
        assert prefix in WRITE_PATH_PREFIXES


@pytest.mark.parametrize("name", INSTALLER_SHADOW_FILES)
def test_installer_shadows_are_write_paths(name):
    """t-2026-08-14-data-root-stale-installer-reti: тень не вернуть коммитом."""
    assert name in WRITE_PATH_PREFIXES
    assert is_write_path(name)
    assert is_write_path(f"./{name}")


def test_installer_shadow_names_are_root_only():
    """Совпадение точное: wiki/setup-brain-v2.sh — заметка, а не установщик."""
    assert not is_write_path("wiki/setup-brain-v2.sh")
    assert not is_write_path("raw/pyproject.toml")
    assert not is_write_path("handoff/install-hooks.sh.md")


def test_installer_shadow_staged_in_data_repo_is_a_violation(tmp_path):
    data = tmp_path / "data"
    system = tmp_path / "system"
    data.mkdir()
    system.mkdir()
    staged = ["wiki/log.md", "setup-brain-v2.sh", "pyproject.toml"]
    assert write_path_violations(
        staged, repo=data, data=data, system=system
    ) == ["setup-brain-v2.sh", "pyproject.toml"]
    # Один корень — легаси-раскладка, установщик в корне законен.
    assert write_path_violations(staged, repo=data, data=data, system=data) == []


def test_installer_shadows_in_lists_only_present_files(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    assert installer_shadows_in(root) == []
    (root / "add-teams-brain.sh").write_text("x\n", encoding="utf-8")
    (root / "setup-brain-v2.sh").write_text("x\n", encoding="utf-8")
    (root / "wiki").mkdir()
    # Порядок канонического списка, а не файловой системы.
    assert installer_shadows_in(root) == ["setup-brain-v2.sh", "add-teams-brain.sh"]
    assert installer_shadows_in(None) == []
    assert installer_shadows_in("") == []


def test_installer_shadow_reason_names_the_damage():
    assert "MEMORY.md" in installer_shadow_reason("setup-brain-v2.sh")
    assert "сборка" in installer_shadow_reason("pyproject.toml")
    assert "установщик" in installer_shadow_reason("install-brain-mcp.sh")
    assert "bootstrap" in installer_shadow_reason("refine-tax-boundaries.sh")


def test_hook_reports_installer_shadow_reason():
    hook = (REPO / "runtime" / "hooks" / "pre-commit-write-path").read_text(encoding="utf-8")
    assert "installer_shadow_reason" in hook


def test_installers_live_only_in_the_system_checkout():
    """Канонические копии — здесь. Валидатор и хук ссылаются на этот же корень."""
    for name in INSTALLER_SHADOW_FILES:
        assert (REPO / name).is_file(), name


def test_docs_name_the_system_checkout_as_the_only_installer_entry():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    guide = (REPO / "spec" / "guide.md").read_text(encoding="utf-8")
    overview = (REPO / "docs" / "architecture-overview.md").read_text(encoding="utf-8")
    contrib = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "живут **только** в системном чекауте" in readme
    assert "перезаписывает ваш `MEMORY.md`" in readme
    assert 'cd "$BRAIN_SYSTEM_PATH"' in guide
    assert "Единственный вход — системный чекаут" in guide
    assert "never run an installer from" in overview
    assert "их канонические копии" in contrib
