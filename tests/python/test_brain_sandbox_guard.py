import os

import pytest

from brain_sandbox_guard import SandboxLaunchError, assert_not_sandbox_agent_launch, sandbox_reason


def test_sandbox_reason_detects_codex_sandbox_network_flag(monkeypatch):
    monkeypatch.setenv("CODEX_SANDBOX_NETWORK_DISABLED", "1")

    assert "CODEX_SANDBOX_NETWORK_DISABLED=1" in sandbox_reason(os.environ)


def test_sandbox_launch_guard_allows_dry_run(monkeypatch):
    monkeypatch.setenv("CODEX_SANDBOX_NETWORK_DISABLED", "1")

    assert_not_sandbox_agent_launch(dry_run=True, action="dashboard launch")


def test_sandbox_launch_guard_blocks_live_agent_launch(monkeypatch):
    monkeypatch.setenv("CODEX_SANDBOX_NETWORK_DISABLED", "1")

    with pytest.raises(SandboxLaunchError) as exc:
        assert_not_sandbox_agent_launch(dry_run=False, action="dashboard launch")

    assert "Refusing dashboard launch inside sandbox" in str(exc.value)
    assert "Use --dry-run" in str(exc.value)
