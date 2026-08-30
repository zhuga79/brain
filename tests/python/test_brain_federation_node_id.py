"""Node identity resolution for federation (t-2026-08-16-multi-user-federation-readines-s1).

Precedence: $BRAIN_NODE_ID > <brain>/config/federation.json node_id >
git config user.email > "anonymous" (non-raising default).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from brain_federation.core import (
    NODE_ID_DEFAULT,
    node_id,
)


@pytest.fixture
def no_git_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Isolate the operator's git config so fallbacks are deterministic."""
    empty = tmp_path / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return empty


def _git_repo(path: Path, email: str) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", email], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test Node"], check=True)


def _write_config(path: Path, payload: str) -> Path:
    cfg = path / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    cfg_file = cfg / "federation.json"
    cfg_file.write_text(payload, encoding="utf-8")
    return cfg_file


def test_node_id_default_when_nothing_configured(tmp_path, no_git_config):
    assert node_id(tmp_path) == NODE_ID_DEFAULT


def test_node_id_missing_vault_never_raises(tmp_path, no_git_config):
    missing = tmp_path / "no-such-vault"
    assert node_id(missing) == NODE_ID_DEFAULT


def test_node_id_fallback_to_git_email(tmp_path):
    _git_repo(tmp_path, "alice@example.org")
    assert node_id(tmp_path) == "alice@example.org"


def test_node_id_config_file_wins_over_git_email(tmp_path):
    _git_repo(tmp_path, "alice@example.org")
    _write_config(tmp_path, json.dumps({"node_id": "cfg-node"}))
    assert node_id(tmp_path) == "cfg-node"


def test_node_id_env_wins_over_config_and_git(tmp_path, monkeypatch):
    _git_repo(tmp_path, "alice@example.org")
    _write_config(tmp_path, json.dumps({"node_id": "cfg-node"}))
    monkeypatch.setenv("BRAIN_NODE_ID", "env-node")
    assert node_id(tmp_path) == "env-node"


def test_node_id_env_blank_ignored(tmp_path, monkeypatch):
    _git_repo(tmp_path, "alice@example.org")
    monkeypatch.setenv("BRAIN_NODE_ID", "   ")
    assert node_id(tmp_path) == "alice@example.org"


def test_node_id_invalid_config_falls_back(tmp_path):
    _git_repo(tmp_path, "bob@example.org")
    _write_config(tmp_path, "not-json{{")
    assert node_id(tmp_path) == "bob@example.org"


def test_node_id_config_missing_key_falls_back(tmp_path):
    _git_repo(tmp_path, "bob@example.org")
    _write_config(tmp_path, json.dumps({"node": {"id": "nested"}}))
    assert node_id(tmp_path) == "bob@example.org"


def test_node_id_config_nonstring_key_falls_back(tmp_path):
    _git_repo(tmp_path, "bob@example.org")
    _write_config(tmp_path, json.dumps({"node_id": 123}))
    assert node_id(tmp_path) == "bob@example.org"


def test_node_id_config_non_dict_falls_back(tmp_path):
    _git_repo(tmp_path, "bob@example.org")
    _write_config(tmp_path, json.dumps(["not", "a", "dict"]))
    assert node_id(tmp_path) == "bob@example.org"


def test_node_id_uses_brain_path_env(tmp_path, monkeypatch):
    _git_repo(tmp_path, "carol@example.org")
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))
    assert node_id() == "carol@example.org"