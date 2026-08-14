"""Tests for runtime/lib/brain_provider.py.

Coverage target: >= 70% of brain_provider.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import pytest

import brain_provider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_matrix(brain: Path, data: dict) -> None:
    (brain / "wiki" / "provider-matrix.json").write_text(json.dumps(data))


def write_routing(brain: Path, data: dict) -> None:
    (brain / "config").mkdir(parents=True, exist_ok=True)
    (brain / "config" / "routing.json").write_text(json.dumps(data), encoding="utf-8")


def write_health(brain: Path, data: dict) -> None:
    (brain / ".provider-health.json").write_text(json.dumps(data))


def _now_str() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _old_str(hours: int = 2) -> str:
    ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_brain(tmp_path: Path) -> Path:
    """Create a minimal Brain directory tree."""
    (tmp_path / "wiki").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Tests: _enrich_candidate
# ---------------------------------------------------------------------------

class TestEnrichCandidate:
    """Tests for _enrich_candidate — the core status-resolution logic."""

    def test_no_health_command_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda c: "/usr/bin/" + c)
        item = brain_provider._enrich_candidate(
            {"provider": "x", "model": "m", "command": "echo hi"}, {}
        )
        assert item["status"] == "unknown"
        assert item["command_present"] is True
        assert item["key"] == "x/m"

    def test_no_health_command_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda c: None)
        item = brain_provider._enrich_candidate(
            {"provider": "x", "model": "m", "command": "doesnotexist"}, {}
        )
        assert item["status"] == "unavailable"
        assert item["command_present"] is False
        assert item["reason"] == "command not found: doesnotexist"

    def test_no_health_empty_command(self) -> None:
        item = brain_provider._enrich_candidate(
            {"provider": "x", "model": "m", "command": ""}, {}
        )
        assert item["status"] == "unavailable"
        assert item["command_present"] is False
        assert item["reason"] == "empty provider command"

    def test_declared_virtual_command_stays_eligible_without_local_binary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(shutil, "which", lambda c: None)
        item = brain_provider._enrich_candidate(
            {
                "provider": "x",
                "model": "m",
                "command": "virtual-runner --model m",
                "execution": "virtual",
            },
            {},
        )
        assert item["status"] == "unknown"
        assert item["command_present"] is False
        assert item["reason"] == "virtual command declared"

    def test_path_assignment_in_command_is_used_for_lookup(self, tmp_path: Path) -> None:
        tool = tmp_path / "bin" / "custom-cli"
        tool.parent.mkdir()
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(0o755)
        command = f"PATH={tool.parent}:$PATH custom-cli --flag"
        item = brain_provider._enrich_candidate(
            {"provider": "x", "model": "m", "command": command},
            {},
        )
        assert item["status"] == "unknown"
        assert item["command_present"] is True

    def test_non_executable_explicit_path_is_unavailable(self, tmp_path: Path) -> None:
        tool = tmp_path / "custom-cli"
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        item = brain_provider._enrich_candidate(
            {"provider": "x", "model": "m", "command": f"{tool} --flag"},
            {},
        )
        assert item["status"] == "unavailable"
        assert item["command_present"] is False
        assert item["reason"] == f"command path is not executable: {tool}"

    def test_env_options_are_parsed_before_assignments_and_executable(self, tmp_path: Path) -> None:
        tool = tmp_path / "bin" / "custom-cli"
        tool.parent.mkdir()
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(0o755)
        command = f"env -i --unset HOME -u USER PATH={tool.parent} -- custom-cli --flag"
        command_present, reason, executable, resolved = brain_provider._command_probe(command)
        assert command_present is True
        assert executable == "custom-cli"
        assert resolved == str(tool)
        assert "local command found" in reason

    @pytest.mark.parametrize(
        ("command", "reason"),
        [
            ("env -u", "env option requires argument: -u"),
            ("env --unset", "env option requires argument: --unset"),
            ("env --bogus cmd", "unsupported env option: --bogus"),
        ],
    )
    def test_env_option_errors_are_precise(self, command: str, reason: str) -> None:
        command_present, actual_reason, executable, resolved = brain_provider._command_probe(command)
        assert command_present is False
        assert actual_reason == reason
        assert executable == ""
        assert resolved == ""

    def test_health_within_ttl_available_becomes_healthy(self) -> None:
        h = {"items": {"x/m": {
            "status": "available",
            "checked_at": _now_str(),
            "ttl_seconds": 900,
            "reason": "ok",
        }}}
        item = brain_provider._enrich_candidate(
            {"provider": "x", "model": "m", "command": ""}, h
        )
        assert item["status"] == "healthy"
        assert item["cached_status"] == "available"

    def test_health_outside_ttl_becomes_stale(self) -> None:
        h = {"items": {"x/m": {
            "status": "available",
            "checked_at": _old_str(2),
            "ttl_seconds": 60,
        }}}
        item = brain_provider._enrich_candidate(
            {"provider": "x", "model": "m", "command": ""}, h
        )
        assert item["status"] == "stale"

    @pytest.mark.parametrize("cached", [
        "unavailable", "rate-limited", "model-not-found", "quota-exhausted", "error",
    ])
    def test_health_propagates_failure_status_within_ttl(self, cached: str) -> None:
        h = {"items": {"x/m": {
            "status": cached,
            "checked_at": _now_str(),
            "ttl_seconds": 900,
        }}}
        item = brain_provider._enrich_candidate(
            {"provider": "x", "model": "m", "command": ""}, h
        )
        assert item["status"] == cached

    def test_invalid_checked_at_falls_back_to_stale(self) -> None:
        h = {"items": {"x/m": {
            "status": "available",
            "checked_at": "not-a-date",
            "ttl_seconds": 900,
        }}}
        item = brain_provider._enrich_candidate(
            {"provider": "x", "model": "m", "command": ""}, h
        )
        # bad date => is_within_ttl stays False => stale
        assert item["status"] == "stale"

    def test_unknown_cached_status_within_ttl_passes_through(self) -> None:
        """A cached_status value not in the explicit set is passed through."""
        h = {"items": {"x/m": {
            "status": "some-custom-status",
            "checked_at": _now_str(),
            "ttl_seconds": 900,
        }}}
        item = brain_provider._enrich_candidate(
            {"provider": "x", "model": "m", "command": ""}, h
        )
        assert item["status"] == "some-custom-status"

    def test_health_key_includes_provider_and_model(self) -> None:
        h = {"items": {}}
        item = brain_provider._enrich_candidate(
            {"provider": "claude", "model": "opus-4.7", "command": ""}, h
        )
        assert item["key"] == "claude/opus-4.7"

    def test_original_candidate_fields_preserved(self) -> None:
        h = {"items": {}}
        c = {"provider": "x", "model": "m", "command": "cmd", "rank": 2, "use_for": "testing"}
        item = brain_provider._enrich_candidate(c, h)
        assert item["rank"] == 2
        assert item["use_for"] == "testing"

    def test_reason_present_in_no_health_path(self) -> None:
        item = brain_provider._enrich_candidate(
            {"provider": "x", "model": "m", "command": ""}, {}
        )
        assert "reason" in item


# ---------------------------------------------------------------------------
# Tests: load_provider_health
# ---------------------------------------------------------------------------

class TestLoadProviderHealth:
    """Tests for load_provider_health."""

    def test_missing_file_returns_empty_items(self, temp_brain: Path) -> None:
        h = brain_provider.load_provider_health(temp_brain)
        assert isinstance(h, dict)
        assert h.get("items", {}) == {}

    def test_loads_present_file(self, temp_brain: Path) -> None:
        write_health(temp_brain, {"items": {"x/m": {"status": "available"}}})
        h = brain_provider.load_provider_health(temp_brain)
        assert "x/m" in h["items"]

    def test_invalid_json_returns_warning(self, temp_brain: Path) -> None:
        (temp_brain / ".provider-health.json").write_text("{bad json}")
        h = brain_provider.load_provider_health(temp_brain)
        assert "warning" in h
        assert h.get("items", {}) == {}

    def test_non_object_json_returns_warning(self, temp_brain: Path) -> None:
        (temp_brain / ".provider-health.json").write_text("[]")
        h = brain_provider.load_provider_health(temp_brain)
        # A JSON array is not a dict => warning path
        assert "warning" in h

    def test_items_key_defaults_to_empty(self, temp_brain: Path) -> None:
        write_health(temp_brain, {})  # no "items" key
        h = brain_provider.load_provider_health(temp_brain)
        assert "items" in h
        assert h["items"] == {}

    def test_source_set_on_loaded_file(self, temp_brain: Path) -> None:
        write_health(temp_brain, {"items": {}})
        h = brain_provider.load_provider_health(temp_brain)
        assert h.get("source", "") != ""


# ---------------------------------------------------------------------------
# Tests: load_provider_matrix
# ---------------------------------------------------------------------------

class TestLoadProviderMatrix:
    """Tests for load_provider_matrix."""

    def test_loads_custom_matrix(self, temp_brain: Path) -> None:
        write_matrix(temp_brain, {
            "version": 1,
            "roles": {"developer": [{"provider": "x", "model": "m", "command": ""}]},
        })
        m = brain_provider.load_provider_matrix(temp_brain)
        assert "roles" in m
        assert "developer" in m["roles"]

    def test_missing_returns_default_matrix(self, temp_brain: Path) -> None:
        m = brain_provider.load_provider_matrix(temp_brain)
        assert isinstance(m, dict)
        assert "roles" in m
        assert m.get("source") == "runtime-default"

    def test_invalid_json_falls_back_to_default(self, temp_brain: Path) -> None:
        (temp_brain / "wiki" / "provider-matrix.json").write_text("{bad json}")
        m = brain_provider.load_provider_matrix(temp_brain)
        assert "warning" in m
        assert m.get("source") == "runtime-default"

    def test_source_set_for_custom_file(self, temp_brain: Path) -> None:
        write_matrix(temp_brain, {"version": 1, "roles": {}})
        m = brain_provider.load_provider_matrix(temp_brain)
        assert "source" in m
        assert "provider-matrix.json" in m["source"]


# ---------------------------------------------------------------------------
# Tests: collect_provider_status (integration)
# ---------------------------------------------------------------------------

class TestCollectProviderStatus:
    """Integration tests for collect_provider_status."""

    def test_returns_roles_dict(self, temp_brain: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda c: "/usr/bin/" + c)
        write_matrix(temp_brain, {
            "version": 1,
            "roles": {
                "developer": [{"provider": "x", "model": "m", "command": "echo", "rank": 1, "use_for": "test"}],
            },
        })
        status = brain_provider.collect_provider_status(temp_brain)
        assert "roles" in status
        assert "developer" in status["roles"]

    def test_healthy_candidate_is_preferred(self, temp_brain: Path) -> None:
        write_matrix(temp_brain, {
            "version": 1,
            "roles": {"developer": [
                {"provider": "x", "model": "m", "command": "echo", "rank": 1, "use_for": ""},
            ]},
        })
        write_health(temp_brain, {"items": {"x/m": {
            "status": "available",
            "checked_at": _now_str(),
            "ttl_seconds": 900,
        }}})
        status = brain_provider.collect_provider_status(temp_brain)
        preferred = status["roles"]["developer"]["preferred"]
        assert preferred is not None
        assert preferred["status"] == "healthy"

    def test_unavailable_candidate_goes_to_unavailable_list(self, temp_brain: Path) -> None:
        write_matrix(temp_brain, {
            "version": 1,
            "roles": {"developer": [
                {"provider": "x", "model": "m", "command": "echo", "rank": 1, "use_for": ""},
            ]},
        })
        write_health(temp_brain, {"items": {"x/m": {
            "status": "unavailable",
            "checked_at": _now_str(),
            "ttl_seconds": 900,
        }}})
        status = brain_provider.collect_provider_status(temp_brain)
        assert status["roles"]["developer"]["preferred"] is None
        assert len(status["roles"]["developer"]["unavailable"]) == 1

    def test_fallback_list_has_second_available(self, temp_brain: Path) -> None:
        write_matrix(temp_brain, {
            "version": 1,
            "roles": {"developer": [
                {"provider": "x", "model": "m1", "command": "echo", "rank": 1, "use_for": ""},
                {"provider": "x", "model": "m2", "command": "echo", "rank": 2, "use_for": ""},
            ]},
        })
        write_health(temp_brain, {"items": {
            "x/m1": {"status": "available", "checked_at": _now_str(), "ttl_seconds": 900},
            "x/m2": {"status": "available", "checked_at": _now_str(), "ttl_seconds": 900},
        }})
        status = brain_provider.collect_provider_status(temp_brain)
        assert len(status["roles"]["developer"]["fallback"]) == 1
        assert status["roles"]["developer"]["fallback"][0]["model"] == "m2"

    def test_top_level_fields_present(self, temp_brain: Path) -> None:
        status = brain_provider.collect_provider_status(temp_brain)
        for field in ("version", "updated", "source", "roles", "routes"):
            assert field in status

    def test_missing_config_reports_it_instead_of_inventing_roles(self, temp_brain: Path) -> None:
        """Без config/routing.json ролей нет, и об этом сказано явно.

        Раньше DEFAULT_MATRIX держал собственную копию политики (6 ролей против
        9 в файле), и они расходились. Теперь вшит только bootstrap-минимум:
        отсутствие настройки не должно выглядеть как настройка."""
        status = brain_provider.collect_provider_status(temp_brain)
        assert status["roles"] == {}
        assert "routing.json" in status["warning"]

    def test_candidates_list_populated(self, temp_brain: Path) -> None:
        write_matrix(temp_brain, {
            "version": 1,
            "roles": {"developer": [
                {"provider": "a", "model": "m1", "command": "echo", "rank": 1, "use_for": ""},
                {"provider": "b", "model": "m2", "command": "echo", "rank": 2, "use_for": ""},
            ]},
        })
        status = brain_provider.collect_provider_status(temp_brain)
        assert len(status["roles"]["developer"]["candidates"]) == 2

    def test_health_warning_propagated(self, temp_brain: Path) -> None:
        (temp_brain / ".provider-health.json").write_text("{bad json}")
        status = brain_provider.collect_provider_status(temp_brain)
        assert status.get("health_warning", "") != ""

    @pytest.mark.parametrize("bad_status", [
        "rate-limited", "model-not-found", "quota-exhausted", "error",
    ])
    def test_failure_statuses_go_to_unavailable_list(
        self, temp_brain: Path, bad_status: str
    ) -> None:
        write_matrix(temp_brain, {
            "version": 1,
            "roles": {"developer": [
                {"provider": "x", "model": "m", "command": "echo", "rank": 1, "use_for": ""},
            ]},
        })
        write_health(temp_brain, {"items": {"x/m": {
            "status": bad_status,
            "checked_at": _now_str(),
            "ttl_seconds": 900,
        }}})
        status = brain_provider.collect_provider_status(temp_brain)
        unavail = status["roles"]["developer"]["unavailable"]
        assert len(unavail) == 1
        assert unavail[0]["status"] == bad_status


# ---------------------------------------------------------------------------
# Tests: helper functions
# ---------------------------------------------------------------------------

class TestHelperFunctions:
    """Tests for matrix_path, health_path, _candidate."""

    def test_matrix_path(self, temp_brain: Path) -> None:
        """Политика лежит в config/, а не в wiki/: wiki — слой знаний."""
        p = brain_provider.matrix_path(temp_brain)
        assert p.name == "routing.json"
        assert "config" in str(p)

    def test_matrix_path_falls_back_to_legacy(self, temp_brain: Path) -> None:
        """Дерево, не прошедшее миграцию, продолжает работать."""
        legacy = temp_brain / "wiki" / "provider-matrix.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("{}", encoding="utf-8")
        assert brain_provider.matrix_path(temp_brain) == legacy

    def test_health_path(self, temp_brain: Path) -> None:
        p = brain_provider.health_path(temp_brain)
        assert ".provider-health.json" in str(p)

    def test_candidate_with_effort(self) -> None:
        c = brain_provider._candidate(1, "claude", "opus", "high", "claude", "planning")
        assert c["effort"] == "high"
        assert c["provider"] == "claude"
        assert c["model"] == "opus"
        assert c["rank"] == 1

    def test_candidate_without_effort(self) -> None:
        c = brain_provider._candidate(2, "gemini", "flash", "", "gemini", "coding")
        assert "effort" not in c

    def test_default_matrix_is_bootstrap_only(self) -> None:
        """Вшитый дефолт — минимум для старта, а не вторая копия политики."""
        dm = brain_provider.DEFAULT_MATRIX
        assert "roles" in dm
        assert dm["roles"] == {}, "политика должна жить в config/routing.json"
        assert dm.get("defaults", {}).get("cli")
        assert brain_provider.MATRIX_VERSION == dm["version"]


# --- список доступных моделей по CLI (/api/models) ---

def test_matrix_models_for_client():
    """Модели берутся из переданной матрицы, а не из вшитого списка."""
    from brain_provider import matrix_models_for_client
    matrix = {
        "roles": {
            "developer": [
                {"provider": "codex", "model": "gpt-5.5"},
                {"provider": "claude", "model": "opus-4.7"},
            ],
        },
        "routes": {"default": ["codex/gpt-5.3", "claude/sonnet-4.6"]},
    }
    codex = matrix_models_for_client(matrix, "codex")
    assert "gpt-5.5" in codex and "gpt-5.3" in codex
    claude = matrix_models_for_client(matrix, "claude")
    assert "opus-4.7" in claude and "sonnet-4.6" in claude
    assert matrix_models_for_client(matrix, "kilocode") == []


def test_parse_live_models_ollama():
    from brain_provider import _parse_live_models
    out = "NAME            ID      SIZE   MODIFIED\nllama3.1:8b     abc     4.7GB  2 days ago\nqwen2.5:14b     def     9GB    5 days ago\n"
    assert _parse_live_models("ollama", out) == ["llama3.1:8b", "qwen2.5:14b"]


def test_list_client_models_config_fallback(tmp_path, monkeypatch):
    import brain_provider
    monkeypatch.setattr(brain_provider, "_models_cache", {})
    monkeypatch.setattr(brain_provider.shutil, "which", lambda _: None)
    monkeypatch.setattr(brain_provider, "_api_models", lambda c, timeout=10: [])
    # Модели берутся из конфига маршрутизации, а не из вшитого списка.
    cfg = tmp_path / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "routing.json").write_text(json.dumps({
        "version": 1,
        "roles": {"architect": [{"provider": "claude", "model": "opus-4.7"}]},
    }), encoding="utf-8")
    payload = brain_provider.list_client_models(tmp_path, "claude")
    assert payload["ok"] and payload["source"] == "config"
    assert payload["available"] is False  # CLI не найден
    assert "opus-4.7" in payload["models"]
    assert "opus" in payload["models"]  # статические алиасы
    # дедупликация с сохранением порядка
    assert len(payload["models"]) == len(set(payload["models"]))


def test_list_client_models_probes_cli_availability(tmp_path, monkeypatch):
    """При наличии бинарника доступность подтверждается вызовом `<cli> --version`."""
    import brain_provider
    monkeypatch.setattr(brain_provider, "_models_cache", {})
    monkeypatch.setattr(brain_provider.shutil, "which", lambda _: "/usr/bin/fake")
    calls = []

    class R:
        returncode = 0
        stdout = "fake-cli 1.2.3\n"
        stderr = ""

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return R()

    monkeypatch.setattr(brain_provider.subprocess, "run", fake_run)
    payload = brain_provider.list_client_models(tmp_path, "codex")
    assert payload["available"] is True
    assert payload["version"] == "fake-cli 1.2.3"
    assert ["codex", "--version"] in calls


def test_list_client_models_cached(tmp_path, monkeypatch):
    import brain_provider
    monkeypatch.setattr(brain_provider, "_models_cache", {})
    monkeypatch.setattr(brain_provider.shutil, "which", lambda _: None)
    first = brain_provider.list_client_models(tmp_path, "codex")
    second = brain_provider.list_client_models(tmp_path, "codex")
    assert first is second  # из кэша


def test_api_models_openai_filters_noise(monkeypatch):
    """Из /v1/models OpenAI берём только чатовые/кодовые модели."""
    import brain_provider
    payload = {"data": [
        {"id": "gpt-5.5"}, {"id": "gpt-5.3-codex"}, {"id": "o3-pro"},
        {"id": "text-embedding-3-large"}, {"id": "gpt-4o-audio-preview"},
        {"id": "whisper-1"}, {"id": "dall-e-3"},
    ]}
    monkeypatch.setattr(brain_provider, "_openai_api_key", lambda: "sk-test")
    monkeypatch.setattr(brain_provider, "_http_get_json", lambda url, headers, timeout: payload)
    models = brain_provider._api_models("codex")
    assert "gpt-5.5" in models and "gpt-5.3-codex" in models and "o3-pro" in models
    assert not any("embedding" in m or "audio" in m or "whisper" in m or "dall-e" in m for m in models)


def test_api_models_anthropic(monkeypatch):
    import brain_provider
    monkeypatch.setattr(brain_provider, "_anthropic_auth_headers", lambda: {"x-api-key": "k"})
    monkeypatch.setattr(brain_provider, "_http_get_json",
                        lambda url, headers, timeout: {"data": [{"id": "claude-fable-5"}, {"id": "claude-opus-4-8"}]})
    assert brain_provider._api_models("claude") == ["claude-fable-5", "claude-opus-4-8"]


def test_api_models_without_credentials(monkeypatch):
    import brain_provider
    monkeypatch.setattr(brain_provider, "_openai_api_key", lambda: "")
    monkeypatch.setattr(brain_provider, "_anthropic_auth_headers", lambda: {})
    monkeypatch.setattr(brain_provider, "_gemini_api_key", lambda: "")
    for client in ("codex", "claude", "gemini"):
        assert brain_provider._api_models(client) == []


def test_list_client_models_prefers_api_over_config(tmp_path, monkeypatch):
    import brain_provider
    monkeypatch.setattr(brain_provider, "_models_cache", {})
    monkeypatch.setattr(brain_provider.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(brain_provider, "_probe_client_version", lambda c, timeout=8: "claude 3.0.0")
    monkeypatch.setattr(brain_provider, "_api_models", lambda c, timeout=10: ["claude-fable-5"])
    payload = brain_provider.list_client_models(tmp_path, "claude")
    assert payload["source"] == "api"
    assert payload["models"] == ["claude-fable-5"]


def test_cli_probe_candidate_keeps_declared_nonlocal_configured():
    import brain_cli.provider as provider_cli

    status, reason = provider_cli.probe_candidate(
        {"provider": "ghost", "model": "v1", "command": "missing-nonlocal-cli", "execution": "remote"},
        timeout=1,
    )
    assert status == "configured"
    assert reason == "remote command declared"


def test_refresh_cache_roundtrip_preserves_nonlocal_eligibility(temp_brain: Path) -> None:
    import argparse
    import brain_cli.provider as provider_cli

    write_routing(temp_brain, {
        "version": brain_provider.MATRIX_VERSION,
        "defaults": {"cli": "claude"},
        "providers": {
            "ghost": {"command": "missing-nonlocal-cli", "enabled": True},
            "claude": {"command": "claude", "model_flag": "--model {model}", "enabled": True},
        },
        "profiles": {
            "implementation": [
                {"rank": 1, "provider": "ghost", "model": "v1", "execution": "virtual"},
                {"rank": 2, "provider": "claude", "model": "sonnet"},
            ],
        },
        "roles": {"developer": {"profile": "implementation"}},
    })

    rc = provider_cli.cmd_refresh(argparse.Namespace(
        brain=str(temp_brain),
        provider="ghost",
        model="v1",
        timeout=1,
        ttl_seconds=3600,
        yes=True,
        json=False,
    ))
    assert rc == 0
    cached = brain_provider.load_provider_health(temp_brain)["items"]["ghost/v1"]
    assert cached["status"] == "configured"
    assert cached["reason"] == "virtual command declared"

    resolved = brain_provider.resolve_for_role(temp_brain, "developer")
    assert resolved["command"] == "missing-nonlocal-cli"
    assert resolved["provider"] == "ghost"
    assert resolved["reason"] == "virtual command declared"
