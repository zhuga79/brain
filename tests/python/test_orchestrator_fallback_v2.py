import argparse
import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "runtime" / "lib"))

loader = importlib.machinery.SourceFileLoader("brain_orchestrator_cli", str(REPO / "runtime" / "bin" / "brain-orchestrator"))
spec = importlib.util.spec_from_loader(loader.name, loader)
brain_orchestrator = importlib.util.module_from_spec(spec)
loader.exec_module(brain_orchestrator)


def _make_executable(path: Path, body: str) -> str:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def _write_task(brain: Path, task_id: str) -> None:
    (brain / "tasks").mkdir(parents=True, exist_ok=True)
    (brain / "tasks" / "active.md").write_text(
        f"- [~] [P1] {task_id} — Smoke task\n"
        "      role: developer   mode: solo\n"
        "      started: 2026-08-14T00:00:00Z\n"
        "      by: smoke-agent\n",
        encoding="utf-8",
    )


def _write_live_v2_routing(brain: Path, primary_cmd: str, fallback_cmd: str) -> None:
    payload = json.loads((REPO / "config" / "routing.json").read_text(encoding="utf-8"))
    payload["roles"] = {"developer": {"profile": "implementation"}}
    payload["profiles"] = {
        "implementation": [
            {"rank": 1, "provider": "fake-primary", "model": "quota", "use_for": "repro"},
            {"rank": 2, "provider": "fake-fallback", "model": "backup", "use_for": "fallback"},
        ]
    }
    payload["providers"] = {
        "fake-primary": {"command": primary_cmd, "model_flag": "", "enabled": True},
        "fake-fallback": {"command": fallback_cmd, "model_flag": "", "enabled": True},
    }
    (brain / "config").mkdir(parents=True, exist_ok=True)
    (brain / "config" / "routing.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _patch_prompt(monkeypatch):
    def fake_write_prompt_file(brain: Path, role: str, task: str, agent: str, workspace_path: Path | None = None) -> Path:
        path = brain_orchestrator.prompt_path_for(brain, task, agent)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# === TASK:\nmock prompt\n", encoding="utf-8")
        return path

    monkeypatch.setattr(brain_orchestrator, "write_prompt_file", fake_write_prompt_file)
    monkeypatch.setattr(brain_orchestrator, "assert_not_sandbox_agent_launch", lambda **kwargs: None)
    monkeypatch.setattr(brain_orchestrator, "run_command_pty", brain_orchestrator.run_command)


def _console_args(brain: Path, task_id: str, *, primary: str = "", fallback: str = "") -> argparse.Namespace:
    return argparse.Namespace(
        brain=str(brain),
        task=task_id,
        role="developer",
        agent="smoke-agent",
        next_task="",
        interactive=False,
        primary=primary,
        fallback=fallback,
        log_file="",
        workspace="",
        no_visible=True,
        wait_visible=False,
        dry_run=False,
        model="",
        effort="",
    )


def test_command_match_requires_normalized_full_argv() -> None:
    assert brain_orchestrator._command_matches("python3 /tmp/a.py --x", "python3 /tmp/a.py --x")
    assert not brain_orchestrator._command_matches("python3 /tmp/a.py", "python3 /tmp/b.py")
    assert not brain_orchestrator._command_matches("python3 /tmp/a.py --mode fast", "python3 /tmp/a.py --mode slow")
    assert not brain_orchestrator._command_matches("/tmp/tool.sh --flag", "/tmp/tool.sh")


def test_get_candidate_by_command_does_not_alias_same_executable(tmp_path) -> None:
    matrix = {
        "roles": {
            "developer": {"profile": "implementation"},
        },
        "profiles": {
            "implementation": [
                {"rank": 1, "provider": "a", "model": "one"},
                {"rank": 2, "provider": "b", "model": "two"},
            ]
        },
        "providers": {
            "a": {"command": "python3 /tmp/a.py", "model_flag": "", "enabled": True},
            "b": {"command": "python3 /tmp/b.py", "model_flag": "", "enabled": True},
        },
    }
    match = brain_orchestrator.get_candidate_by_command(matrix, "python3 /tmp/a.py")
    miss = brain_orchestrator.get_candidate_by_command(matrix, "python3 /tmp/c.py")

    assert match["provider"] == "a"
    assert match["command"] == "python3 /tmp/a.py"
    assert miss["provider"] == "python3"
    assert miss["command"] == "python3 /tmp/c.py"
    assert miss["model"] == "unknown"


def test_console_auto_fallback_uses_next_v2_candidate(monkeypatch, tmp_path, capsys):
    _patch_prompt(monkeypatch)
    brain = tmp_path / "brain"
    task_id = "t-auto-fallback"
    marker = tmp_path / "fallback.ok"
    primary = _make_executable(
        tmp_path / "primary.sh",
        "#!/usr/bin/env bash\n"
        "echo 'HTTP 429 Too Many Requests RESOURCE_EXHAUSTED' >&2\n"
        "exit 42\n",
    )
    fallback = _make_executable(
        tmp_path / "fallback.sh",
        f"#!/usr/bin/env bash\nprintf 'fallback-ran' > {marker}\nexit 0\n",
    )
    _write_task(brain, task_id)
    _write_live_v2_routing(brain, primary, fallback)

    rc = brain_orchestrator.cmd_console(_console_args(brain, task_id))

    assert rc == 0
    assert marker.read_text(encoding="utf-8") == "fallback-ran"
    stderr = capsys.readouterr().err
    assert "AttributeError" not in stderr
    assert "fallback command succeeded" in stderr
    handoff = (brain / "handoff" / "ORCHESTRATOR_HANDOFF.md").read_text(encoding="utf-8")
    assert "reason: fallback" in handoff
    assert "provider_from" in handoff
    assert "provider_to" in handoff
    assert '"provider": "fake-primary"' in handoff
    assert '"provider": "fake-fallback"' in handoff


def test_console_non_limit_failure_skips_fallback(monkeypatch, tmp_path, capsys):
    _patch_prompt(monkeypatch)
    brain = tmp_path / "brain"
    task_id = "t-no-fallback"
    marker = tmp_path / "fallback.skip"
    primary = _make_executable(
        tmp_path / "primary.sh",
        "#!/usr/bin/env bash\n"
        "echo 'plain failure' >&2\n"
        "exit 7\n",
    )
    fallback = _make_executable(
        tmp_path / "fallback.sh",
        f"#!/usr/bin/env bash\nprintf 'unexpected' > {marker}\nexit 0\n",
    )
    _write_task(brain, task_id)
    _write_live_v2_routing(brain, primary, fallback)

    rc = brain_orchestrator.cmd_console(_console_args(brain, task_id))

    assert rc == 7
    assert not marker.exists()
    stderr = capsys.readouterr().err
    assert "no limit pattern detected; fallback skipped" in stderr


def test_console_fallback_failure_returns_fallback_rc(monkeypatch, tmp_path, capsys):
    _patch_prompt(monkeypatch)
    brain = tmp_path / "brain"
    task_id = "t-all-fail"
    primary = _make_executable(
        tmp_path / "primary.sh",
        "#!/usr/bin/env bash\n"
        "echo 'HTTP 429 Too Many Requests RESOURCE_EXHAUSTED' >&2\n"
        "exit 42\n",
    )
    fallback = _make_executable(
        tmp_path / "fallback.sh",
        "#!/usr/bin/env bash\n"
        "echo 'fallback failed' >&2\n"
        "exit 9\n",
    )
    _write_task(brain, task_id)
    _write_live_v2_routing(brain, primary, fallback)

    rc = brain_orchestrator.cmd_console(_console_args(brain, task_id))

    assert rc == 9
    stderr = capsys.readouterr().err
    assert "AttributeError" not in stderr
    assert "fallback command failed rc=9" in stderr


def test_console_explicit_primary_still_auto_selects_routed_fallback(monkeypatch, tmp_path):
    _patch_prompt(monkeypatch)
    brain = tmp_path / "brain"
    task_id = "t-explicit-primary"
    marker = tmp_path / "fallback.explicit"
    primary = _make_executable(
        tmp_path / "primary.sh",
        "#!/usr/bin/env bash\n"
        "echo 'HTTP 429 Too Many Requests RESOURCE_EXHAUSTED' >&2\n"
        "exit 42\n",
    )
    fallback = _make_executable(
        tmp_path / "fallback.sh",
        f"#!/usr/bin/env bash\nprintf 'explicit-ok' > {marker}\nexit 0\n",
    )
    _write_task(brain, task_id)
    _write_live_v2_routing(brain, primary, fallback)

    rc = brain_orchestrator.cmd_console(_console_args(brain, task_id, primary=primary))

    assert rc == 0
    assert marker.read_text(encoding="utf-8") == "explicit-ok"


def test_console_explicit_override_without_exact_routed_match_uses_synthetic_metadata(monkeypatch, tmp_path):
    _patch_prompt(monkeypatch)
    brain = tmp_path / "brain"
    task_id = "t-explicit-override"
    marker = tmp_path / "fallback.synthetic"
    primary = _make_executable(
        tmp_path / "primary.sh",
        "#!/usr/bin/env bash\n"
        "echo 'HTTP 429 Too Many Requests RESOURCE_EXHAUSTED' >&2\n"
        "exit 42\n",
    )
    fallback = _make_executable(
        tmp_path / "fallback.sh",
        f"#!/usr/bin/env bash\nprintf 'synthetic-ok' > {marker}\nexit 0\n",
    )
    _write_task(brain, task_id)
    _write_live_v2_routing(brain, primary, fallback)

    override = f"{primary} --override-flag"
    rc = brain_orchestrator.cmd_console(_console_args(brain, task_id, primary=override))

    assert rc == 0
    assert marker.read_text(encoding="utf-8") == "synthetic-ok"
    handoff = (brain / "handoff" / "ORCHESTRATOR_HANDOFF.md").read_text(encoding="utf-8")
    assert '--override-flag' in handoff
    assert '"provider": "bash"' in handoff
    assert '"provider": "fake-primary"' not in handoff
    assert '"model": "unknown"' in handoff
