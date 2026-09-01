"""t-2026-08-14-model-signature-contract-align: one completion policy.

CLI, MCP, dashboard, app queue and workspace must resolve the recorded
`model:` field through brain_core.model_signature. Normal completion needs a
versioned identifier. `unsigned` is a legacy hatch: explicit, opt-in, audited.
Archive records already signed (including historical `model: unsigned`) stay
readable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_app import queue
from brain_core.model_signature import (
    ALLOW_UNSIGNED_ENV,
    AGENT_MODEL_ENV,
    AUDIT_OP,
    UNSIGNED_TOKEN,
    ModelSignatureError,
    complete_cli_argv,
    queue_action_argv,
    resolve_completion_model,
    validate_model_signature,
)
import brain_workspace


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "active.md").write_text(
        "# Active Tasks\n\n"
        "- [ ] [P1] t-open — Open task\n"
        "      role: developer   mode: solo\n"
        "      acceptance: ok\n",
        encoding="utf-8",
    )
    (tasks / "done.md").write_text(
        "# Done Tasks\n\n"
        "- [x] [P1] t-old-signed — Already signed\n"
        "      role: developer   mode: solo\n"
        "      by: agent-old\n"
        "      model: openai-gpt-5.4\n"
        "      completed: 2026-08-01T00:00:00Z\n\n"
        "- [x] [P2] t-old-unsigned — Legacy unsigned archive\n"
        "      role: developer   mode: solo\n"
        "      by: agent-old\n"
        "      model: unsigned\n"
        "      completed: 2026-05-29T00:00:00Z\n",
        encoding="utf-8",
    )
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "log.md").write_text("# Log\n\n", encoding="utf-8")
    return tmp_path


# ── validator ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model",
    ["openai-gpt-5.4", "claude-opus-4-8", "gemini-2.5-pro", "grok-4.6"],
)
def test_validate_accepts_versioned_models(model):
    assert validate_model_signature(model) == model
    assert queue.validate_model_signature(model) == model


@pytest.mark.parametrize(
    "model",
    [
        "",
        "   ",
        None,
        UNSIGNED_TOKEN,
        "placeholder-summary-text",
        "cleanup",
        "summary",
        "openai-gpt",
        "claude-opus",
        "probe-model",
        "evil-model",
        "test-model",
        "bad model 5.4",
    ],
)
def test_validate_rejects_blank_placeholder_and_unversioned(model):
    with pytest.raises((ModelSignatureError, ValueError)):
        validate_model_signature(model)
    with pytest.raises((ModelSignatureError, ValueError)):
        queue.validate_model_signature(model)


def test_validate_strips_whitespace_of_versioned_model():
    assert validate_model_signature("  grok-4.6  ") == "grok-4.6"


# ── resolver ─────────────────────────────────────────────────────────────────


def test_resolve_uses_explicit_argument_over_env(monkeypatch):
    monkeypatch.setenv(AGENT_MODEL_ENV, "claude-opus-4-8")
    resolved = resolve_completion_model("openai-gpt-5.4")
    assert resolved.value == "openai-gpt-5.4"
    assert resolved.unsigned is False
    assert resolved.source == "argument"


def test_resolve_falls_back_to_brain_agent_model(monkeypatch):
    monkeypatch.setenv(AGENT_MODEL_ENV, "gemini-2.5-pro")
    resolved = resolve_completion_model("")
    assert resolved.value == "gemini-2.5-pro"
    assert resolved.unsigned is False
    assert resolved.source == AGENT_MODEL_ENV


def test_resolve_missing_model_is_an_error_not_unsigned(monkeypatch):
    monkeypatch.delenv(AGENT_MODEL_ENV, raising=False)
    monkeypatch.delenv(ALLOW_UNSIGNED_ENV, raising=False)
    with pytest.raises(ModelSignatureError, match="model signature required"):
        resolve_completion_model("")
    with pytest.raises(ModelSignatureError, match="model signature required"):
        resolve_completion_model("   ")


def test_resolve_unsigned_without_hatch_is_an_error(monkeypatch):
    monkeypatch.delenv(ALLOW_UNSIGNED_ENV, raising=False)
    with pytest.raises(ModelSignatureError, match="real model"):
        resolve_completion_model(UNSIGNED_TOKEN)


def test_resolve_brain_require_model_zero_is_not_a_hatch(monkeypatch):
    monkeypatch.delenv(AGENT_MODEL_ENV, raising=False)
    monkeypatch.setenv("BRAIN_REQUIRE_MODEL", "0")
    with pytest.raises(ModelSignatureError, match="model signature required"):
        resolve_completion_model("")


@pytest.mark.parametrize("flag", ["1", "true", "YES", "on"])
def test_resolve_allow_unsigned_env_is_explicit_opt_in(monkeypatch, flag):
    monkeypatch.delenv(AGENT_MODEL_ENV, raising=False)
    monkeypatch.setenv(ALLOW_UNSIGNED_ENV, flag)
    resolved = resolve_completion_model("")
    assert resolved.value == UNSIGNED_TOKEN
    assert resolved.unsigned is True
    assert resolved.source == "allow-unsigned"
    assert "hatch=" in resolved.audit_extra


def test_resolve_allow_unsigned_kwarg_records_unsigned(monkeypatch):
    monkeypatch.delenv(AGENT_MODEL_ENV, raising=False)
    monkeypatch.delenv(ALLOW_UNSIGNED_ENV, raising=False)
    resolved = resolve_completion_model("", allow_unsigned=True)
    assert resolved.value == UNSIGNED_TOKEN
    assert resolved.unsigned is True
    assert resolved.source == "allow-unsigned"


def test_resolve_explicit_unsigned_still_needs_hatch(monkeypatch):
    monkeypatch.delenv(ALLOW_UNSIGNED_ENV, raising=False)
    resolved = resolve_completion_model(UNSIGNED_TOKEN, allow_unsigned=True)
    assert resolved.value == UNSIGNED_TOKEN
    assert resolved.unsigned is True


def test_resolve_hatch_does_not_override_versioned_env(monkeypatch):
    monkeypatch.setenv(AGENT_MODEL_ENV, "grok-4.6")
    monkeypatch.setenv(ALLOW_UNSIGNED_ENV, "1")
    resolved = resolve_completion_model("")
    assert resolved.value == "grok-4.6"
    assert resolved.unsigned is False


def test_resolve_isolated_environ_mapping_does_not_read_process_env(monkeypatch):
    monkeypatch.setenv(AGENT_MODEL_ENV, "claude-opus-4-8")
    with pytest.raises(ModelSignatureError, match="model signature required"):
        resolve_completion_model("", environ={})
    resolved = resolve_completion_model("", environ={AGENT_MODEL_ENV: "grok-4.6"})
    assert resolved.value == "grok-4.6"


# ── adapter argv: dashboard/CLI must not inject unsigned ─────────────────────


def test_complete_cli_argv_passes_model_and_hatch_flag():
    assert complete_cli_argv("t-1", "agent-1", "openai-gpt-5.4") == [
        "complete", "t-1", "--as", "agent-1", "--model", "openai-gpt-5.4",
    ]
    assert complete_cli_argv("t-1", "agent-1", "", allow_unsigned=True) == [
        "complete", "t-1", "--as", "agent-1", "--allow-unsigned",
    ]
    argv = complete_cli_argv("t-1", "agent-1", "")
    assert UNSIGNED_TOKEN not in argv
    assert "--model" not in argv


def test_dashboard_complete_argv_does_not_default_to_unsigned():
    argv = queue_action_argv("complete", "t-open", "dash-agent")
    assert argv[0] == "complete"
    assert UNSIGNED_TOKEN not in argv
    assert "--model" not in argv
    with_model = queue_action_argv(
        "complete", "t-open", "dash-agent", model="openai-gpt-5.4",
    )
    assert with_model[-2:] == ["--model", "openai-gpt-5.4"]
    hatch = queue_action_argv(
        "complete", "t-open", "dash-agent", allow_unsigned=True,
    )
    assert "--allow-unsigned" in hatch
    assert UNSIGNED_TOKEN not in hatch


# ── app queue adapter ────────────────────────────────────────────────────────


def test_queue_complete_requires_versioned_model(brain, monkeypatch):
    monkeypatch.delenv(AGENT_MODEL_ENV, raising=False)
    monkeypatch.delenv(ALLOW_UNSIGNED_ENV, raising=False)
    queue.take("t-open", "agent-1", brain)
    with pytest.raises(ModelSignatureError):
        queue.complete("t-open", "agent-1", "", brain)
    assert "t-open" in queue.active_text(brain)
    assert "t-open" not in queue.done_text(brain)


def test_queue_complete_records_versioned_model(brain):
    queue.take("t-open", "agent-1", brain)
    resolved = queue.complete("t-open", "agent-1", "claude-opus-4-8", brain)
    assert resolved.value == "claude-opus-4-8"
    assert "model: claude-opus-4-8" in queue.done_text(brain)
    assert AUDIT_OP not in (brain / "wiki" / "log.md").read_text(encoding="utf-8")


def test_queue_complete_hatch_is_audited(brain, monkeypatch):
    monkeypatch.delenv(AGENT_MODEL_ENV, raising=False)
    queue.take("t-open", "agent-1", brain)
    resolved = queue.complete(
        "t-open", "agent-1", "", brain, allow_unsigned=True,
    )
    assert resolved.value == UNSIGNED_TOKEN
    done = queue.done_text(brain)
    assert "model: unsigned" in done
    log = (brain / "wiki" / "log.md").read_text(encoding="utf-8")
    assert AUDIT_OP in log
    assert "t-open" in log
    assert "agent-1" in log
    assert "hatch=" in log


def test_queue_complete_env_model(brain, monkeypatch):
    monkeypatch.setenv(AGENT_MODEL_ENV, "grok-4.6")
    queue.take("t-open", "agent-1", brain)
    queue.complete("t-open", "agent-1", "", brain)
    assert "model: grok-4.6" in queue.done_text(brain)


def test_existing_signed_and_legacy_unsigned_archive_records_remain_readable(brain):
    done = queue.load_done(brain)
    ids = {task["id"] for task in done}
    assert "t-old-signed" in ids
    assert "t-old-unsigned" in ids
    text = queue.done_text(brain)
    assert "model: openai-gpt-5.4" in text
    assert "model: unsigned" in text


def test_taskfile_writer_still_accepts_historical_unsigned_token(brain):
    """Writer records the string it is given; policy sits in the adapters."""
    from brain_core import taskfile, paths

    queue.take("t-open", "agent-1", brain)
    taskfile.complete(
        paths.active_file(brain),
        paths.done_file(brain),
        "t-open",
        "agent-1",
        UNSIGNED_TOKEN,
    )
    assert "model: unsigned" in queue.done_text(brain)


# ── workspace adapter ────────────────────────────────────────────────────────


def _local_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    (workspace / "TASKS.md").write_text(
        """# Local Tasks

- [~] [P1] local-001 - Draft local rules
      role: developer
      acceptance: Rules drafted.
      started: 2026-08-14T10:00:00Z
      by: agent-a
""",
        encoding="utf-8",
    )
    (workspace / "LOG.md").write_text("# Local Log\n", encoding="utf-8")
    return workspace


def test_workspace_complete_rejects_unversioned_model(tmp_path):
    workspace = _local_workspace(tmp_path)
    with pytest.raises((ModelSignatureError, ValueError)):
        brain_workspace.complete_local_task(workspace, "local-001", "agent-a", "test-model")
    content = (workspace / "TASKS.md").read_text(encoding="utf-8")
    assert "- [~]" in content
    assert "model: test-model" not in content


def test_workspace_complete_hatch_records_unsigned_and_audit(tmp_path, monkeypatch):
    monkeypatch.delenv(AGENT_MODEL_ENV, raising=False)
    workspace = _local_workspace(tmp_path)
    task = brain_workspace.complete_local_task(
        workspace, "local-001", "agent-a", "", allow_unsigned=True,
    )
    assert task.state == "done"
    content = (workspace / "TASKS.md").read_text(encoding="utf-8")
    assert "model: unsigned" in content
    log = (workspace / "LOG.md").read_text(encoding="utf-8")
    assert AUDIT_OP in log or "unsigned" in log


# ── queue CLI adapter ────────────────────────────────────────────────────────


def test_queue_cli_complete_requires_model_and_supports_hatch(brain, capsys, monkeypatch):
    monkeypatch.delenv(AGENT_MODEL_ENV, raising=False)
    monkeypatch.delenv(ALLOW_UNSIGNED_ENV, raising=False)
    queue.take("t-open", "agent-1", brain)
    assert queue.main([
        "--brain", str(brain), "complete", "t-open", "--as", "agent-1",
    ]) == 1
    err = capsys.readouterr().err
    assert "model" in err.lower()
    assert "t-open" in queue.active_text(brain)

    assert queue.main([
        "--brain", str(brain), "complete", "t-open", "--as", "agent-1",
        "--allow-unsigned",
    ]) == 0
    out = capsys.readouterr().out.strip()
    assert out == UNSIGNED_TOKEN
    assert "model: unsigned" in queue.done_text(brain)
    assert AUDIT_OP in (brain / "wiki" / "log.md").read_text(encoding="utf-8")
