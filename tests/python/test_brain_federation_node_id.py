"""Node identity resolution for federation (t-2026-08-16-multi-user-federation-readines-s1).

Precedence: $BRAIN_NODE_ID > <brain>/config/federation.json node_id >
git config user.email (explicit opt-in only) > "anonymous" (non-raising default).

Git user.email is operator PII and must not leak into a journal synced to
every federation peer unless the operator explicitly opts in via
$BRAIN_NODE_ID_FROM_GIT=1 or "node_id_from_git": true in federation.json.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from brain_federation.core import (
    NODE_ID_DEFAULT,
    node_audit_extra,
    node_id,
)
from brain_federation import core as federation_core


@pytest.fixture(autouse=True)
def _isolate_node_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAIN_NODE_ID", raising=False)
    monkeypatch.delenv("BRAIN_NODE_ID_FROM_GIT", raising=False)
    federation_core._git_email_cache.clear()


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


def test_node_id_git_email_not_leaked_by_default(tmp_path, no_git_config):
    # operator git email exists but is NOT opted in -> stay anonymous
    _git_repo(tmp_path, "alice@example.org")
    assert node_id(tmp_path) == NODE_ID_DEFAULT


def test_node_id_git_email_used_when_opted_in_via_env(tmp_path, no_git_config, monkeypatch):
    _git_repo(tmp_path, "alice@example.org")
    monkeypatch.setenv("BRAIN_NODE_ID_FROM_GIT", "1")
    assert node_id(tmp_path) == "alice@example.org"


def test_node_id_git_email_used_when_opted_in_via_config(tmp_path, no_git_config):
    _git_repo(tmp_path, "alice@example.org")
    _write_config(tmp_path, json.dumps({"node_id_from_git": True}))
    assert node_id(tmp_path) == "alice@example.org"


def test_node_id_config_file_wins_over_git_email(tmp_path, no_git_config, monkeypatch):
    _git_repo(tmp_path, "alice@example.org")
    monkeypatch.setenv("BRAIN_NODE_ID_FROM_GIT", "1")
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
    assert node_id(tmp_path) == NODE_ID_DEFAULT


def test_node_id_invalid_config_falls_back(tmp_path, no_git_config):
    _git_repo(tmp_path, "bob@example.org")
    _write_config(tmp_path, "not-json{{")
    assert node_id(tmp_path) == NODE_ID_DEFAULT


def test_node_id_config_missing_key_falls_back(tmp_path, no_git_config):
    _git_repo(tmp_path, "bob@example.org")
    _write_config(tmp_path, json.dumps({"node": {"id": "nested"}}))
    assert node_id(tmp_path) == NODE_ID_DEFAULT


def test_node_id_config_nonstring_key_falls_back(tmp_path, no_git_config):
    _git_repo(tmp_path, "bob@example.org")
    _write_config(tmp_path, json.dumps({"node_id": 123}))
    assert node_id(tmp_path) == NODE_ID_DEFAULT


def test_node_id_config_non_dict_falls_back(tmp_path, no_git_config):
    _git_repo(tmp_path, "bob@example.org")
    _write_config(tmp_path, json.dumps(["not", "a", "dict"]))
    assert node_id(tmp_path) == NODE_ID_DEFAULT


def test_node_id_uses_brain_path_env(tmp_path, no_git_config, monkeypatch):
    _git_repo(tmp_path, "carol@example.org")
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))
    monkeypatch.setenv("BRAIN_NODE_ID_FROM_GIT", "1")
    assert node_id() == "carol@example.org"


def test_node_id_env_injection_newline_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_NODE_ID", "x\n## [2026-08-30T00:00:00Z] task-done | t-fake | attacker | model=x")
    with pytest.raises(ValueError):
        node_id(tmp_path)


def test_node_id_env_injection_pipe_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_NODE_ID", "node|status=ok")
    with pytest.raises(ValueError):
        node_id(tmp_path)


def test_node_id_config_injection_raises(tmp_path):
    _write_config(tmp_path, json.dumps({"node_id": "attacker\n## [2026-08-30T00:00:00Z] task-done | t-fake | attacker"}))
    with pytest.raises(ValueError):
        node_id(tmp_path)


def test_node_id_allows_email_charset(tmp_path, no_git_config, monkeypatch):
    monkeypatch.setenv("BRAIN_NODE_ID", "alice+tag@example.org")
    assert node_id(tmp_path) == "alice+tag@example.org"


def test_node_id_git_email_env_zero_overrides_config(tmp_path, no_git_config, monkeypatch):
    _git_repo(tmp_path, "alice@example.org")
    _write_config(tmp_path, json.dumps({"node_id_from_git": True}))
    monkeypatch.setenv("BRAIN_NODE_ID_FROM_GIT", "0")
    assert node_id(tmp_path) == NODE_ID_DEFAULT


def test_node_id_opted_in_invalid_git_email_raises(tmp_path, no_git_config, monkeypatch):
    _git_repo(tmp_path, "not an email with spaces")
    monkeypatch.setenv("BRAIN_NODE_ID_FROM_GIT", "1")
    with pytest.raises(ValueError, match="git config user.email"):
        node_id(tmp_path)


def test_node_audit_extra_places_node_first():
    assert node_audit_extra("n1", "status=ok") == "node=n1 | status=ok"
    assert node_audit_extra("n1") == "node=n1"
