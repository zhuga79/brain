"""t-2026-08-21-brain-roles-brain-doctrine-ro: brain-doctrine roles.

Roles live in the system checkout. `brain-doctrine roles` must list them via
iter_system_files, including when cwd / BRAIN_PATH is the data root and the
data tree has no roles/.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
BIN = REPO / "runtime" / "bin" / "brain-doctrine"


def _load_doctrine():
    loader = importlib.machinery.SourceFileLoader("brain_doctrine_under_test", str(BIN))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _run(mod, argv: list[str], capsys) -> tuple[int, str, str]:
    with patch.object(sys, "argv", ["brain-doctrine", *argv]):
        try:
            code = mod.main()
        except SystemExit as exc:
            code = int(exc.code or 0)
    cap = capsys.readouterr()
    return int(code or 0), cap.out, cap.err


def _role_text(name: str) -> str:
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
def split_roles(tmp_path, monkeypatch):
    data = tmp_path / "data"
    system = tmp_path / "system"
    (data / "wiki").mkdir(parents=True)
    (system / "roles").mkdir(parents=True)
    (system / "doctrine").mkdir()
    (system / "roles" / "developer.md").write_text(_role_text("developer"), encoding="utf-8")
    (system / "roles" / "maintainer.md").write_text(_role_text("maintainer"), encoding="utf-8")
    (system / "doctrine" / "tax-boundaries.md").write_text("# tax\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PATH", str(data))
    monkeypatch.setenv("BRAIN_SYSTEM_PATH", str(system))
    return data, system


class TestDoctrineRolesCommand:
    def test_roles_lists_system_roles_when_data_has_none(self, split_roles, capsys):
        data, _system = split_roles
        assert not (data / "roles").exists()
        mod = _load_doctrine()
        code, out, err = _run(mod, ["roles"], capsys)
        assert code == 0, err
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        assert "developer" in lines
        assert "maintainer" in lines
        assert "tax-boundaries" not in lines

    def test_roles_json_lists_slug_and_system_path(self, split_roles, capsys):
        _data, system = split_roles
        mod = _load_doctrine()
        code, out, err = _run(mod, ["roles", "--json"], capsys)
        assert code == 0, err
        payload = json.loads(out)
        slugs = {entry["slug"] for entry in payload["roles"]}
        assert slugs == {"developer", "maintainer"}
        by_slug = {entry["slug"]: entry for entry in payload["roles"]}
        assert by_slug["developer"]["path"] == str(system / "roles" / "developer.md")

    def test_roles_slug_prints_role_file(self, split_roles, capsys):
        mod = _load_doctrine()
        code, out, err = _run(mod, ["roles", "maintainer"], capsys)
        assert code == 0, err
        assert "# Role: maintainer" in out
        assert "developer" not in out.splitlines()

    def test_roles_slug_json_includes_content(self, split_roles, capsys):
        _data, system = split_roles
        mod = _load_doctrine()
        code, out, err = _run(mod, ["roles", "developer", "--json"], capsys)
        assert code == 0, err
        payload = json.loads(out)
        assert payload["slug"] == "developer"
        assert payload["path"] == str(system / "roles" / "developer.md")
        assert "# Role: developer" in payload["content"]

    def test_roles_unknown_slug_exits_1(self, split_roles, capsys):
        mod = _load_doctrine()
        code, out, err = _run(mod, ["roles", "nosuch"], capsys)
        assert code == 1
        assert "nosuch" in err

    def test_roles_rejects_path_traversal_slug(self, split_roles, capsys):
        mod = _load_doctrine()
        code, _out, err = _run(mod, ["roles", "../MEMORY"], capsys)
        assert code == 1
        assert "invalid role slug" in err

    def test_roles_empty_prints_placeholder(self, tmp_path, monkeypatch, capsys):
        data = tmp_path / "data"
        system = tmp_path / "system"
        data.mkdir()
        system.mkdir()
        monkeypatch.setenv("BRAIN_PATH", str(data))
        monkeypatch.setenv("BRAIN_SYSTEM_PATH", str(system))
        mod = _load_doctrine()
        code, out, err = _run(mod, ["roles"], capsys)
        assert code == 0, err
        assert "no role" in out.lower()

    def test_help_mentions_roles(self, capsys):
        mod = _load_doctrine()
        code, out, err = _run(mod, ["--help"], capsys)
        assert code == 0
        text = out + err
        assert "roles" in text

    def test_commands_constant_includes_roles(self):
        mod = _load_doctrine()
        assert "roles" in set(mod.COMMANDS)
        assert {"list", "show", "search", "roles"} <= set(mod.COMMANDS)
