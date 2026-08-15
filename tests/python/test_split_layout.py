"""t-2026-08-14-private-drop-system: data tree has no exclusive system dirs."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_core.layers import INSTALLER_SHADOW_FILES
from brain_core.paths import iter_system_files, resolve_system_asset
from brain_wiki.pages import all_page_slugs
from brain_wiki.validators import (
    validate_all,
    validate_installer_shadows,
    validate_system_paths_not_restored,
)
from brain_wiki.writers import lint_wiki


DATA_DIRS = ("wiki", "tasks", "raw", "council", "handoff", "learning", "prd", ".locks")
EXCLUSIVE_SYSTEM_DIRS = ("runtime", "tests", "spec", "docs")
SHADOW_SYSTEM_DIRS = EXCLUSIVE_SYSTEM_DIRS + ("roles", "doctrine", "skills", "config")
DROPPED_SYSTEM_DIRS = EXCLUSIVE_SYSTEM_DIRS + ("roles", "teams", "doctrine", "skills")


def _page(title: str, typ: str, body: str) -> str:
    return (
        "---\n"
        f"title: {title}\n"
        f"type: {typ}\n"
        "created: 2026-08-14\n"
        "updated: 2026-08-14\n"
        "curation: agent\n"
        "protected: false\n"
        "source_policy: advisory\n"
        "tags: []\n"
        "sources: []\n"
        "related: []\n"
        "---\n"
        f"{body}\n"
    )


@pytest.fixture
def split_roots(tmp_path, monkeypatch):
    data = tmp_path / "data"
    system = tmp_path / "system"
    for name in DATA_DIRS:
        (data / name).mkdir(parents=True)
    (data / "tasks" / "active.md").write_text("# Active\n", encoding="utf-8")
    (data / "tasks" / "done.md").write_text("# Done\n", encoding="utf-8")
    (data / "wiki" / "index.md").write_text("# Index\n[[work-notes]]\n", encoding="utf-8")
    (data / "wiki" / "log.md").write_text("# Log\n", encoding="utf-8")
    (data / "wiki" / "work-notes.md").write_text(
        _page("Work Notes", "concept", "See [[decision-foo]]."),
        encoding="utf-8",
    )
    (system / "roles").mkdir(parents=True)
    (system / "docs" / "decisions").mkdir(parents=True)
    (system / "runtime" / "bin").mkdir(parents=True)
    (system / "config").mkdir()
    (system / "roles" / "developer.md").write_text(
        "---\ntype: role\ndoctrine: []\nmodel_tier: fast\nwrites: [code]\n---\n"
        "# Role: developer\n",
        encoding="utf-8",
    )
    (system / "config" / "routing.json").write_text(
        '{"version": 2, "profiles": {"fast": [{"rank": 1, "provider": "none",'
        ' "model": "x", "command": "true"}]}, "providers": {"none": {}},'
        ' "roles": {"developer": {"profile": "fast"}}}\n',
        encoding="utf-8",
    )
    (system / "docs" / "decisions" / "decision-foo.md").write_text(
        _page("Decision Foo", "decision", "ADR"),
        encoding="utf-8",
    )
    monkeypatch.setenv("BRAIN_PATH", str(data))
    monkeypatch.setenv("BRAIN_SYSTEM_PATH", str(system))
    return data, system


def test_split_layout_data_dirs_have_no_exclusive_system_copy(split_roots):
    data, _system = split_roots
    for name in DROPPED_SYSTEM_DIRS:
        assert not (data / name).exists(), name


def test_split_layout_validate_green(split_roots):
    data, _system = split_roots
    issues = validate_all(data)
    errors = [i for i in issues if i.severity == "ERROR"]
    assert errors == [], errors


def test_split_layout_all_page_slugs_include_system_docs(split_roots):
    data, _system = split_roots
    assert all_page_slugs(data) == {"decision-foo", "index", "log", "work-notes"}


def test_split_layout_lint_accepts_data_link_to_system_page(split_roots):
    data, _system = split_roots
    issues = lint_wiki(data)
    missing = [i for i in issues if "missing wikilink target" in i.message]
    assert missing == [], issues


def test_split_layout_lint_counts_system_links_as_inbound(split_roots):
    data, system = split_roots
    (data / "wiki" / "work-notes.md").write_text(
        _page("Work Notes", "concept", "No local inbound."),
        encoding="utf-8",
    )
    (system / "docs" / "decisions" / "decision-foo.md").write_text(
        _page("Decision Foo", "decision", "See [[work-notes]]."),
        encoding="utf-8",
    )
    issues = lint_wiki(data)
    assert not any(
        i.path == "wiki/work-notes.md" and "orphan page has no inbound wikilinks" in i.message
        for i in issues
    ), issues


def test_split_layout_lint_warns_on_cross_root_duplicate_slug(split_roots):
    data, system = split_roots
    (data / "wiki" / "decision-foo.md").write_text(
        _page("Decision Foo", "decision", "Local copy."),
        encoding="utf-8",
    )
    issues = lint_wiki(data)
    assert any(
        "possible duplicate title/slug group decision-foo" in i.message
        for i in issues
    ), issues


def test_split_layout_all_page_slugs_ignore_raw_and_dedupe_symlinked_system_docs(tmp_path, monkeypatch):
    data = tmp_path / "data"
    system = tmp_path / "system"
    for name in DATA_DIRS:
        (data / name).mkdir(parents=True)
    (data / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    (data / "wiki" / "log.md").write_text("# Log\n", encoding="utf-8")
    (data / "wiki" / "work-notes.md").write_text(_page("Work Notes", "concept", "Body."), encoding="utf-8")
    (data / "tasks" / "active.md").write_text("# Active\n", encoding="utf-8")
    (data / "tasks" / "done.md").write_text("# Done\n", encoding="utf-8")
    (data / "raw" / "decision-foo.md").write_text("---\ntitle: raw\n", encoding="utf-8")
    (system / "docs" / "shared").mkdir(parents=True)
    (system / "docs" / "shared" / "decision-foo.md").write_text(
        _page("Decision Foo", "decision", "ADR."),
        encoding="utf-8",
    )
    (system / "docs" / "decisions").mkdir(parents=True)
    (system / "docs" / "decisions" / "decision-foo.md").symlink_to(system / "docs" / "shared" / "decision-foo.md")
    monkeypatch.setenv("BRAIN_PATH", str(data))
    monkeypatch.setenv("BRAIN_SYSTEM_PATH", str(system))

    assert all_page_slugs(data) == {"decision-foo", "index", "log", "work-notes"}


def test_root_install_all_page_slugs_still_include_docs(tmp_path, monkeypatch):
    root = tmp_path / "brain"
    for name in ("wiki", "tasks", "raw", "docs", "docs/decisions"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    (root / "wiki" / "log.md").write_text("# Log\n", encoding="utf-8")
    (root / "wiki" / "work-notes.md").write_text(_page("Work Notes", "concept", "[[decision-foo]]"), encoding="utf-8")
    (root / "docs" / "decisions" / "decision-foo.md").write_text(
        _page("Decision Foo", "decision", "ADR."),
        encoding="utf-8",
    )
    (root / "tasks" / "active.md").write_text("# Active\n", encoding="utf-8")
    (root / "tasks" / "done.md").write_text("# Done\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PATH", str(root))
    monkeypatch.delenv("BRAIN_SYSTEM_PATH", raising=False)

    assert "decision-foo" in all_page_slugs(root)
    assert not any("missing wikilink target" in i.message for i in lint_wiki(root))


def test_split_layout_runtime_back_is_red(split_roots):
    data, _system = split_roots
    (data / "runtime").mkdir()
    issues = validate_system_paths_not_restored(data)
    assert any(
        i.severity == "ERROR"
        and i.path == "runtime/"
        and "системный путь восстановлен в приватном дереве" in i.message
        for i in issues
    ), issues
    errors = [i for i in validate_all(data) if i.severity == "ERROR"]
    assert any(i.path == "runtime/" for i in errors), errors


@pytest.mark.parametrize("name", SHADOW_SYSTEM_DIRS)
def test_split_layout_system_shadow_dirs_are_red(split_roots, name):
    data, _system = split_roots
    target = data / name
    target.mkdir(parents=True)
    issues = validate_system_paths_not_restored(data)
    assert any(
        i.severity == "ERROR"
        and i.path == f"{name}/"
        and "системный путь восстановлен в приватном дереве" in i.message
        for i in issues
    ), issues


@pytest.mark.parametrize("name", INSTALLER_SHADOW_FILES)
def test_split_layout_installer_shadow_is_red(split_roots, name):
    """t-2026-08-14-data-root-stale-installer-reti: installer back in data is red."""
    data, system = split_roots
    (data / name).write_text("# stale shadow\n", encoding="utf-8")
    issues = validate_installer_shadows(data)
    match = [i for i in issues if i.path == name]
    assert match, issues
    assert match[0].severity == "ERROR"
    assert "installer-тень в дереве данных" in match[0].message
    # Диагностика называет канонический файл, а не «что-то не так».
    assert str(system / name) in match[0].message
    errors = [i for i in validate_all(data) if i.severity == "ERROR"]
    assert any(i.path == name for i in errors), errors


def test_split_layout_installer_shadow_reason_is_specific(split_roots):
    data, _system = split_roots
    (data / "setup-brain-v2.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (data / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (data / "add-teams-brain.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    by_path = {i.path: i.message for i in validate_installer_shadows(data)}
    assert "перезаписывает операторский MEMORY.md" in by_path["setup-brain-v2.sh"]
    assert "сборка и зависимости ядра" in by_path["pyproject.toml"]
    assert "bootstrap-скрипт" in by_path["add-teams-brain.sh"]


def test_split_layout_clean_data_root_has_no_installer_issue(split_roots):
    data, _system = split_roots
    assert validate_installer_shadows(data) == []


def test_single_root_installer_in_root_is_allowed(tmp_path, monkeypatch):
    """Legacy: один корень — установщик в корне и есть канонический вход."""
    root = tmp_path / "brain"
    for name in ("wiki", "tasks", "raw"):
        (root / name).mkdir(parents=True)
    for name in INSTALLER_SHADOW_FILES:
        (root / name).write_text("# legacy single root\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PATH", str(root))
    monkeypatch.delenv("BRAIN_SYSTEM_PATH", raising=False)

    assert validate_installer_shadows(root) == []


def test_split_layout_data_team_override_is_allowed(split_roots):
    data, _system = split_roots
    (data / "teams").mkdir()
    (data / "teams" / "insurance-fraud.md").write_text(
        "---\n"
        "title: Insurance Fraud\n"
        "type: team\n"
        "roles: [developer]\n"
        "---\n",
        encoding="utf-8",
    )
    issues = validate_system_paths_not_restored(data)
    assert issues == [], issues


def test_split_layout_roles_resolve_from_system(split_roots):
    data, system = split_roots
    resolved = resolve_system_asset("roles/developer.md", brain=data)
    assert resolved == system / "roles" / "developer.md"
    stems = {path.stem for path in iter_system_files("roles", "*.md", brain=data)}
    assert "developer" in stems
    assert not (data / "roles").exists()
