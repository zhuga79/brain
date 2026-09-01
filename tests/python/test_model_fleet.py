"""t-2026-08-30-cyclical-model-list-actualizat: чистая логика реестра моделей.

build_registry должен нормализовать живой список в канонический плоский
реестр без дубликатов и с однозначными ключами клиент/модель; render_report —
давать читаемый отчёт с теми же данными; unit-спека цикла — собираться по
правилам systemd и уважать политику расписания.
"""

from __future__ import annotations

from brain_app.cycles import model_fleet, systemd


def test_build_registry_prefixes_and_deduplicates() -> None:
    clients = {
        "claude": {"available": True, "version": "2.1", "models": ["opus", "sonnet", "opus"], "source": "config"},
        "opencode": {"available": True, "version": "1.18", "models": ["opencode/claude-sonnet-5", "big-pickle"], "source": "live"},
    }
    roles = {"architect": {"preferred": "claude/opus", "model": "opus", "status": "available"}}
    registry = model_fleet.build_registry(clients, roles, "config/routing.json")

    assert registry["version"] == 1
    assert registry["policy"] == "config/routing.json"
    assert registry["stale_after_hours"] > 0
    assert registry["updated_utc"]

    assert set(registry["clients"]) == {"claude", "opencode"}
    assert registry["clients"]["opencode"]["models"] == [
        "opencode/claude-sonnet-5",
        "opencode/big-pickle",
    ]
    # все модели приводятся к однозначной форме клиент/модель
    assert "opus" not in registry["live_model_ids"]
    assert "claude/opus" in registry["live_model_ids"]
    # дубликаты схлопнуты
    assert registry["live_model_ids"].count("claude/opus") == 1
    assert "opencode/claude-sonnet-5" in registry["live_model_ids"]
    assert registry["roles"]["architect"]["preferred"] == "claude/opus"


def test_build_registry_empty_clients() -> None:
    registry = model_fleet.build_registry({}, {}, policy="p")
    assert registry["clients"] == {}
    assert registry["live_model_ids"] == []


def test_render_report_covers_registry_data() -> None:
    registry = model_fleet.build_registry(
        {"claude": {"available": True, "version": "2.1", "models": ["opus"], "source": "config"}},
        {"architect": {"preferred": "claude/opus", "model": "opus", "status": "available"}},
        "config/routing.json",
    )
    text = model_fleet.render_report(registry)
    assert "# Model Fleet Report" in text
    assert "| claude |" in text
    assert "claude/opus" in text
    assert "## Роли → preferred" in text


def test_enabled_clients_falls_back() -> None:
    assert model_fleet.enabled_clients({}) == list(model_fleet.FALLBACK_CLIENTS)
    matrix = {"providers": {"gemini": {"enabled": False}, "claude": {"enabled": True}}}
    assert model_fleet.enabled_clients(matrix) == ["claude"]


def test_unit_spec_valid_and_daily() -> None:
    import argparse

    args = argparse.Namespace(brain=None)
    unit = model_fleet.unit(args)
    assert unit.name == model_fleet.NAME
    # имя юнита проходит проверку systemd
    assert systemd.UNIT_NAME_RE.match(unit.name)
    timer = dict(unit.timer_options)
    assert timer.get("OnCalendar") == "daily"
    assert timer.get("Persistent") == "true"


def test_model_fleet_issues_flag_missing_and_stale(tmp_path) -> None:
    from brain_wiki.writers import model_fleet_issues

    brain = tmp_path / "brain"
    (brain / "config").mkdir(parents=True)
    issue = model_fleet_issues(brain)
    assert len(issue) == 1 and issue[0].severity == "WARN"
    assert "run brain-model-fleet --apply" in issue[0].message

    # свежий реестр — тишина
    from brain_core import clock
    import json

    (brain / "config" / "model-fleet.json").write_text(json.dumps({
        "version": 1,
        "updated_utc": clock.utc_now(),
        "stale_after_hours": 24,
        "live_model_ids": ["claude/claude-sonnet-5"],
    }), encoding="utf-8")
    assert model_fleet_issues(brain) == []

    # протухший реестр — WARN stale
    (brain / "config" / "model-fleet.json").write_text(json.dumps({
        "version": 1,
        "updated_utc": "2020-01-01T00:00:00Z",
        "stale_after_hours": 24,
        "live_model_ids": ["claude/claude-sonnet-4-6"],
    }), encoding="utf-8")
    issues = model_fleet_issues(brain)
    assert len(issues) == 1
    assert "stale" in issues[0].message.lower()