"""t-2026-08-21-brain-roles-brain-doctrine-ro: MEMORY.md role pointers.

The constitution must not send agents to ~/brain/roles or to a
brain-doctrine subcommand that does not exist. brain-validate catches that
by machine, not by reading the file with eyes.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

from brain_wiki.validators import (
    DOCTRINE_COMMANDS,
    validate_all,
    validate_memory_role_pointers,
)

REPO = Path(__file__).resolve().parents[2]


def _errors(issues):
    return [i for i in issues if i.severity == "ERROR"]


def _make_data(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    for name in ("raw", "wiki", "tasks"):
        (data / name).mkdir(parents=True)
    (data / "tasks" / "active.md").write_text("# Active\n", encoding="utf-8")
    (data / "tasks" / "done.md").write_text("# Done\n", encoding="utf-8")
    (data / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    (data / "wiki" / "log.md").write_text("# Log\n", encoding="utf-8")
    return data


def _role(name: str) -> str:
    return (
        "---\n"
        "type: role\n"
        "doctrine: []\n"
        "model_tier: fast\n"
        "writes: [code]\n"
        "---\n"
        f"# Role: {name}\n"
    )


@pytest.fixture
def split_roots(tmp_path, monkeypatch):
    data = _make_data(tmp_path)
    system = tmp_path / "system"
    (system / "roles").mkdir(parents=True)
    (system / "roles" / "developer.md").write_text(_role("developer"), encoding="utf-8")
    monkeypatch.setenv("BRAIN_PATH", str(data))
    monkeypatch.setenv("BRAIN_SYSTEM_PATH", str(system))
    return data, system


_CANON = """# MEMORY

Роль лежит в `$BRAIN_SYSTEM_PATH/roles/<role>.md`.
Список — `brain-doctrine roles`.
ОБЯЗАТЕЛЬНО прочитай `$BRAIN_SYSTEM_PATH/roles/<твоя-роль>.md`.
"""

_DEAD = """# MEMORY

Полный текст роли лежит в `roles/<role>.md`.
Список — `brain-doctrine roles` или `ls roles/`.
ОБЯЗАТЕЛЬНО прочитай `~/brain/roles/<твоя-роль>.md`.
"""


class TestValidateMemoryRolePointers:
    def test_none_brain_is_silent(self):
        assert validate_memory_role_pointers(None) == []

    def test_missing_memory_is_silent(self, split_roots):
        data, _system = split_roots
        assert validate_memory_role_pointers(data) == []

    def test_empty_memory_is_silent(self, split_roots):
        data, _system = split_roots
        (data / "MEMORY.md").write_text("", encoding="utf-8")
        assert validate_memory_role_pointers(data) == []

    def test_dead_data_roles_path_is_error_in_split_root(self, split_roots):
        data, _system = split_roots
        (data / "MEMORY.md").write_text(_DEAD, encoding="utf-8")
        errors = _errors(validate_memory_role_pointers(data))
        assert errors, "dead ~/brain/roles pointer must be an ERROR"
        assert any("~/brain/roles" in i.message or "дереве данных" in i.message for i in errors)

    def test_ls_roles_is_error_when_data_has_no_roles(self, split_roots):
        data, _system = split_roots
        (data / "MEMORY.md").write_text(
            "Список — `ls roles/`.\n",
            encoding="utf-8",
        )
        errors = _errors(validate_memory_role_pointers(data))
        assert any("ls roles" in i.message for i in errors)

    def test_unknown_doctrine_subcommand_is_error(self, split_roots):
        data, _system = split_roots
        (data / "MEMORY.md").write_text(
            "Список — `brain-doctrine nosuch`.\n",
            encoding="utf-8",
        )
        errors = _errors(validate_memory_role_pointers(data))
        assert any("nosuch" in i.message for i in errors)

    def test_canonical_system_path_and_roles_command_are_ok(self, split_roots):
        data, _system = split_roots
        (data / "MEMORY.md").write_text(_CANON, encoding="utf-8")
        issues = validate_memory_role_pointers(data)
        assert _errors(issues) == [], issues

    def test_unicode_noise_does_not_false_positive(self, split_roots):
        data, _system = split_roots
        (data / "MEMORY.md").write_text(
            _CANON + "\nemoji 🧠 и «роли» без пути.\n",
            encoding="utf-8",
        )
        assert _errors(validate_memory_role_pointers(data)) == []

    def test_system_memory_is_checked_too(self, split_roots):
        data, system = split_roots
        (data / "MEMORY.md").write_text(_CANON, encoding="utf-8")
        (system / "MEMORY.md").write_text(_DEAD, encoding="utf-8")
        errors = _errors(validate_memory_role_pointers(data))
        assert errors
        assert any(i.path.endswith("MEMORY.md") for i in errors)

    def test_template_memory_is_checked(self, split_roots):
        data, system = split_roots
        (data / "MEMORY.md").write_text(_CANON, encoding="utf-8")
        template = system / "runtime" / "templates" / "v2" / "MEMORY.md"
        template.parent.mkdir(parents=True)
        template.write_text(_DEAD, encoding="utf-8")
        errors = _errors(validate_memory_role_pointers(data))
        assert any("runtime/templates/v2/MEMORY.md" in i.path for i in errors)

    def test_single_root_data_roles_pointer_ok_when_roles_exist(self, tmp_path, monkeypatch):
        brain = _make_data(tmp_path)
        (brain / "roles").mkdir()
        (brain / "roles" / "developer.md").write_text(_role("developer"), encoding="utf-8")
        (brain / "MEMORY.md").write_text(_DEAD, encoding="utf-8")
        monkeypatch.setenv("BRAIN_PATH", str(brain))
        monkeypatch.delenv("BRAIN_SYSTEM_PATH", raising=False)
        assert _errors(validate_memory_role_pointers(brain)) == []

    def test_validate_all_includes_dead_pointer(self, split_roots):
        data, _system = split_roots
        (data / "MEMORY.md").write_text(_DEAD, encoding="utf-8")
        errors = _errors(validate_all(data))
        assert any(
            "roles" in i.message.lower() or "brain-doctrine" in i.message or i.path.endswith("MEMORY.md")
            for i in errors
        ), errors

    def test_doctrine_commands_match_cli(self):
        loader = importlib.machinery.SourceFileLoader(
            "brain_doctrine_cmd_sync",
            str(REPO / "runtime" / "bin" / "brain-doctrine"),
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        assert set(mod.COMMANDS) == set(DOCTRINE_COMMANDS)
        assert "roles" in DOCTRINE_COMMANDS


class TestRepoMemoryInstruction:
    def test_system_memory_points_at_system_roles(self):
        text = (REPO / "MEMORY.md").read_text(encoding="utf-8")
        assert "~/brain/roles" not in text
        assert "`ls roles/`" not in text
        assert "brain-doctrine roles" in text
        assert "$BRAIN_SYSTEM_PATH/roles" in text

    def test_template_memory_matches_system_pointers(self):
        text = (REPO / "runtime" / "templates" / "v2" / "MEMORY.md").read_text(encoding="utf-8")
        assert "~/brain/roles" not in text
        assert "`ls roles/`" not in text
        assert "brain-doctrine roles" in text
        assert "$BRAIN_SYSTEM_PATH/roles" in text

    def test_split_root_docs_name_system_owner(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        assert "$BRAIN_SYSTEM_PATH/roles" in readme
        assert "brain-doctrine roles" in readme
        arch = (REPO / "docs" / "architecture-overview.md").read_text(encoding="utf-8")
        assert "$BRAIN_SYSTEM_PATH/roles" in arch
        assert "brain-doctrine roles" in arch
