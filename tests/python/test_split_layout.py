"""t-2026-08-14-private-drop-system: data tree has no exclusive system dirs."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_core.paths import iter_system_files, resolve_system_asset
from brain_wiki.validators import (
    validate_all,
    validate_system_paths_not_restored,
)


DATA_DIRS = ("wiki", "tasks", "raw", "council", "handoff", "learning", "prd", ".locks")
EXCLUSIVE_SYSTEM_DIRS = ("runtime", "tests", "spec", "docs")
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


def test_split_layout_roles_resolve_from_system(split_roots):
    data, system = split_roots
    resolved = resolve_system_asset("roles/developer.md", brain=data)
    assert resolved == system / "roles" / "developer.md"
    stems = {path.stem for path in iter_system_files("roles", "*.md", brain=data)}
    assert "developer" in stems
    assert not (data / "roles").exists()
