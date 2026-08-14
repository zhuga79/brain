"""t-2026-08-10-routing-resolver: один резолвер роль → команда.

Роутинг читали два несовместимых пути: bash-строка `cli_for_<role>` из
.cli-mapping.sh (одна команда на роль, без рангов и здоровья — поэтому у
brain-launch и brain-council не было fallback вовсе) и матрица через
brain_provider. Порядок приоритета теперь записан в одном месте.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import brain_provider

REPO = Path(__file__).resolve().parent.parent.parent
BIN = REPO / "runtime" / "bin" / "brain-provider"


def write_routing(brain: Path, roles: dict, providers: dict | None = None, defaults: str = "claude") -> None:
    (brain / "config").mkdir(parents=True, exist_ok=True)
    payload = {
        "version": brain_provider.MATRIX_VERSION,
        "defaults": {"cli": defaults},
        "roles": roles,
    }
    if providers is not None:
        payload["providers"] = providers
    (brain / "config" / "routing.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def cand(rank: int, provider: str, model: str, command: str) -> dict:
    return {"rank": rank, "provider": provider, "model": model, "command": command}


@pytest.fixture
def single_root(tmp_path, monkeypatch):
    """Корни выставлены явно: единый install, где system root равен data root.

    Без этого `brain_system_path()` брал `BRAIN_SYSTEM_PATH` из шелла, и пустое
    дерево `tmp_path` дочитывало роли и routing.json из боевого чекаута —
    проверки «конфигурации нет» проходили или падали в зависимости от того,
    кто запускает прогон.
    """
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))
    monkeypatch.setenv("BRAIN_SYSTEM_PATH", str(tmp_path))
    return tmp_path


@pytest.fixture
def brain(single_root, monkeypatch):
    monkeypatch.setenv("BRAIN_DISABLE_SKILL_ROUTING", "1")
    return single_root


class TestOrder:
    def test_lowest_rank_wins(self, brain):
        write_routing(brain, {"developer": [
            cand(2, "codex", "gpt", "codex"),
            cand(1, "opencode", "default", "opencode run"),
        ]})
        r = brain_provider.resolve_for_role(brain, "developer")
        assert r["command"] == "opencode run"
        assert r["source"] == "config"

    def test_override_beats_config(self, brain):
        write_routing(brain, {"developer": [cand(1, "opencode", "d", "opencode run")]})
        r = brain_provider.resolve_for_role(brain, "developer", override="claude --model opus")
        assert r["command"] == "claude --model opus"
        assert r["source"] == "override"

    def test_missing_role_falls_back_to_defaults_cli(self, brain):
        write_routing(brain, {"developer": [cand(1, "opencode", "d", "opencode run")]}, defaults="claude")
        r = brain_provider.resolve_for_role(brain, "нет-такой-роли")
        assert r["command"] == "claude"
        assert r["source"] == "default"
        assert any("не описана" in w for w in r["warnings"])

    def test_underscore_role_name_still_resolves(self, brain):
        """В bash роли писались через подчёркивание — старые записи не теряем."""
        write_routing(brain, {"tax_advisor": [cand(1, "claude", "opus", "claude")]})
        assert brain_provider.resolve_for_role(brain, "tax-advisor")["command"] == "claude"


class TestHealthAndEnabled:
    def _health(self, brain: Path, key: str, status: str) -> None:
        (brain / ".provider-health.json").write_text(json.dumps({
            "items": {key: {"status": status, "reason": "проба",
                            "checked_at": "2099-01-01T00:00:00Z", "ttl_seconds": 10 ** 9}},
        }), encoding="utf-8")

    def test_unhealthy_candidate_is_skipped(self, brain):
        write_routing(brain, {"developer": [
            cand(1, "codex", "gpt-5.5", "codex"),
            cand(2, "claude", "sonnet", "claude --model sonnet"),
        ]})
        self._health(brain, "codex/gpt-5.5", "quota-exhausted")
        r = brain_provider.resolve_for_role(brain, "developer")
        assert r["command"] == "claude --model sonnet"
        assert any("quota-exhausted" in s for s in r["skipped"])

    def test_missing_local_candidate_is_skipped_for_installed_fallback(self, brain, monkeypatch):
        write_routing(brain, {"developer": [
            cand(1, "ghost", "v1", "missing-local-cli --model v1"),
            cand(2, "claude", "sonnet", "claude --model sonnet"),
        ]})

        def fake_which(cmd: str, path: str | None = None) -> str | None:
            if cmd == "claude":
                return "/usr/bin/claude"
            return None

        monkeypatch.setattr(brain_provider.shutil, "which", fake_which)
        r = brain_provider.resolve_for_role(brain, "developer")
        assert r["command"] == "claude --model sonnet"
        assert any("command not found: missing-local-cli" in s for s in r["skipped"])

    @pytest.mark.parametrize(
        ("execution", "reason"),
        [("virtual", "virtual command declared"), ("remote", "remote command declared")],
    )
    def test_declared_nonlocal_candidate_remains_eligible(self, brain, monkeypatch, execution, reason):
        write_routing(brain, {"developer": [
            {
                "rank": 1,
                "provider": "ghost",
                "model": "v1",
                "command": "missing-nonlocal-cli --model v1",
                "execution": execution,
            },
            cand(2, "claude", "sonnet", "claude --model sonnet"),
        ]})
        monkeypatch.setattr(brain_provider.shutil, "which", lambda cmd, path=None: None)
        r = brain_provider.resolve_for_role(brain, "developer")
        assert r["command"] == "missing-nonlocal-cli --model v1"
        assert r["reason"] == reason

    def test_non_executable_explicit_path_is_skipped_with_precise_reason(self, brain, tmp_path, monkeypatch):
        tool = tmp_path / "custom-cli"
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        write_routing(brain, {"developer": [
            cand(1, "ghost", "v1", f"{tool} --model v1"),
            cand(2, "claude", "sonnet", "claude --model sonnet"),
        ]})

        def fake_which(cmd: str, path: str | None = None) -> str | None:
            if cmd == "claude":
                return "/usr/bin/claude"
            return None

        monkeypatch.setattr(brain_provider.shutil, "which", fake_which)
        r = brain_provider.resolve_for_role(brain, "developer")
        assert r["command"] == "claude --model sonnet"
        assert any(f"command path is not executable: {tool}" in s for s in r["skipped"])

    def test_disabled_provider_is_skipped_even_when_healthy(self, brain):
        """enabled — решение оператора, оно сильнее «сейчас отвечает»."""
        write_routing(
            brain,
            {"reviewer": [cand(1, "gemini", "pro", "gemini"), cand(2, "claude", "opus", "claude")]},
            providers={"gemini": {"enabled": False, "reason": "отключён оператором"}},
        )
        self._health(brain, "gemini/pro", "available")
        r = brain_provider.resolve_for_role(brain, "reviewer")
        assert r["command"] == "claude"
        assert any("отключён оператором" in s for s in r["skipped"])

    def test_not_provider_excludes_the_author(self, brain):
        """Правило диверсификации: ревьюер не идёт к провайдеру автора."""
        write_routing(brain, {"reviewer": [
            cand(1, "claude", "opus", "claude --model opus"),
            cand(2, "opencode", "d", "opencode run"),
        ]})
        r = brain_provider.resolve_for_role(brain, "reviewer", not_provider="claude")
        assert r["command"] == "opencode run"
        assert any("диверсификации" in s for s in r["skipped"])

    def test_all_candidates_unavailable_still_returns_a_command(self, brain):
        """Отказ запускать роль хуже запуска на дефолте — но с предупреждением."""
        write_routing(brain, {"developer": [cand(1, "codex", "gpt", "codex")]},
                      providers={"codex": {"enabled": False, "reason": "квота"}})
        r = brain_provider.resolve_for_role(brain, "developer")
        assert r["command"] == "claude"
        assert r["source"] == "default"
        assert any("ни один кандидат не доступен" in w for w in r["warnings"])


class TestBrokenConfig:
    def test_corrupted_config_falls_back_and_warns(self, brain):
        (brain / "config").mkdir()
        (brain / "config" / "routing.json").write_text("{ сломано", encoding="utf-8")
        r = brain_provider.resolve_for_role(brain, "developer")
        assert r["command"] == "claude"
        assert any("invalid matrix file" in w for w in r["warnings"])

    def test_absent_config_names_the_missing_file(self, brain):
        r = brain_provider.resolve_for_role(brain, "developer")
        assert r["command"] == "claude"
        assert any("routing.json" in w for w in r["warnings"])


class TestSystemRootResolution:
    """t-2026-08-14-pytest-system-path-isolation: оба корня заданы тестом.

    Раньше ветку «конфигурация лежит в системном корне» никто не проверял: её
    случайно исполняло окружение оператора, если прогон запускали из шелла с
    выставленным `BRAIN_SYSTEM_PATH`. Тесты изолированы, поэтому обе ветки —
    и фолбэк без переменной, и разделённый layout — проверяются явно.
    """

    def _system_root(self, tmp_path: Path) -> Path:
        system = tmp_path / "system"
        write_routing(system, {"developer": [cand(1, "opencode", "d", "opencode run")]})
        return system

    def test_unset_system_path_resolves_to_the_data_root(self, tmp_path, monkeypatch):
        """Production-фолбэк: переменной нет — системный корень равен data root."""
        from brain_core.paths import brain_system_path

        data = tmp_path / "data"
        data.mkdir()
        monkeypatch.setenv("BRAIN_PATH", str(data))
        monkeypatch.delenv("BRAIN_SYSTEM_PATH", raising=False)

        assert brain_system_path() == data
        assert brain_provider.matrix_path(data) == data / "config" / "routing.json"

    def test_unset_system_path_keeps_the_missing_config_warning(self, tmp_path, monkeypatch):
        """Единый install без конфигурации обязан жаловаться, а не искать соседа."""
        data = tmp_path / "data"
        data.mkdir()
        monkeypatch.setenv("BRAIN_PATH", str(data))
        monkeypatch.delenv("BRAIN_SYSTEM_PATH", raising=False)
        monkeypatch.setenv("BRAIN_DISABLE_SKILL_ROUTING", "1")

        r = brain_provider.resolve_for_role(data, "developer")
        assert r["source"] == "default"
        assert any("routing.json" in w for w in r["warnings"])

    def test_split_layout_reads_the_config_from_the_system_root(self, tmp_path, monkeypatch):
        """Разделённый layout: data root пуст, политика приходит из системного."""
        data = tmp_path / "data"
        data.mkdir()
        system = self._system_root(tmp_path)
        monkeypatch.setenv("BRAIN_PATH", str(data))
        monkeypatch.setenv("BRAIN_SYSTEM_PATH", str(system))
        monkeypatch.setenv("BRAIN_DISABLE_SKILL_ROUTING", "1")

        assert brain_provider.matrix_path(data) == system / "config" / "routing.json"
        r = brain_provider.resolve_for_role(data, "developer")
        assert r["command"] == "opencode run"
        assert r["source"] == "config"

    def test_data_root_config_wins_over_the_system_one(self, tmp_path, monkeypatch):
        """Локальный оверрайд сильнее системного: иначе его нельзя было бы задать."""
        data = tmp_path / "data"
        write_routing(data, {"developer": [cand(1, "claude", "opus", "claude --model opus")]})
        system = self._system_root(tmp_path)
        monkeypatch.setenv("BRAIN_PATH", str(data))
        monkeypatch.setenv("BRAIN_SYSTEM_PATH", str(system))
        monkeypatch.setenv("BRAIN_DISABLE_SKILL_ROUTING", "1")

        assert brain_provider.matrix_path(data) == data / "config" / "routing.json"
        assert brain_provider.resolve_for_role(data, "developer")["command"] == "claude --model opus"


class TestCliCommand:
    def _run(self, brain: Path, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, BRAIN_PATH=str(brain), BRAIN_DISABLE_SKILL_ROUTING="1")
        env.pop("BRAIN_CLI_OVERRIDE", None)
        return subprocess.run([sys.executable, str(BIN), "cli", *args],
                              capture_output=True, text=True, env=env, check=False)

    def test_prints_command_for_role(self, brain):
        write_routing(brain, {"developer": [cand(1, "opencode", "d", "opencode run")]})
        res = self._run(brain, "--role", "developer")
        assert res.returncode == 0
        assert res.stdout.strip() == "opencode run"

    def test_broken_config_exits_zero_with_warning_on_stderr(self, brain):
        """Запуск не должен вставать из-за конфигурации: дефолт + WARN."""
        (brain / "config").mkdir()
        (brain / "config" / "routing.json").write_text("{ сломано", encoding="utf-8")
        res = self._run(brain, "--role", "developer")
        assert res.returncode == 0
        assert res.stdout.strip() == "claude"
        assert "WARN" in res.stderr

    def test_env_override_is_honoured(self, brain):
        write_routing(brain, {"developer": [cand(1, "opencode", "d", "opencode run")]})
        env = dict(os.environ, BRAIN_PATH=str(brain), BRAIN_CLI_OVERRIDE="claude --model opus",
                   BRAIN_DISABLE_SKILL_ROUTING="1")
        res = subprocess.run([sys.executable, str(BIN), "cli", "--role", "developer"],
                             capture_output=True, text=True, env=env, check=False)
        assert res.stdout.strip() == "claude --model opus"

    def test_json_output_carries_the_reason(self, brain):
        write_routing(brain, {"developer": [cand(1, "opencode", "d", "opencode run")]})
        res = self._run(brain, "--role", "developer", "--json")
        payload = json.loads(res.stdout)
        assert payload["command"] == "opencode run"
        assert payload["source"] == "config"

    def test_explain_reports_precise_missing_command_reason(self, brain):
        write_routing(brain, {"developer": [
            cand(1, "ghost", "v1", "missing-local-cli --model v1"),
            cand(2, "claude", "sonnet", "claude --model sonnet"),
        ]})
        res = self._run(brain, "--role", "developer", "--explain")
        assert res.returncode == 0
        assert res.stdout.strip() == "claude --model sonnet"
        assert "command not found: missing-local-cli" in res.stderr


def test_cli_mapping_file_is_gone():
    """Вторая реализация маршрутизации удалена, а не оставлена «на всякий случай»."""
    assert not (REPO / ".cli-mapping.sh").exists()
    common = (REPO / "runtime" / "bin" / "brain-common").read_text(encoding="utf-8")
    # Проверяем подключение, а не упоминание: комментарий о том, что было
    # раньше, полезен и остаётся.
    assert '. "$BRAIN/.cli-mapping.sh"' not in common
    assert "${!var:-}" not in common, "bash больше не читает cli_for_<role> косвенно"
    assert "brain-provider" in common


def test_federation_no_longer_lists_the_removed_file():
    from brain_federation.core import RUNTIME_PATHS

    assert ".cli-mapping.sh" not in RUNTIME_PATHS


class TestSkillPinScope:
    """Закрепление клиента скиллом действует на задачу, а не на всю роль."""

    def _brain_with_skill(self, brain: Path, requires: str = "") -> Path:
        (brain / "skills" / "playwright").mkdir(parents=True)
        (brain / "skills" / "playwright" / "SKILL.md").write_text(
            "---\nname: playwright\ntype: mcp\napplies_to: [developer, qa]\n"
            "supported_clients: [claude]\nmcp_command: npx\n---\nbody\n", encoding="utf-8")
        (brain / "tasks").mkdir()
        block = "- [ ] [P1] t-x — Задача\n      role: developer\n"
        if requires:
            block += f"      requires: [{requires}]\n"
        (brain / "tasks" / "active.md").write_text(block, encoding="utf-8")
        write_routing(brain, {"developer": [cand(1, "opencode", "d", "opencode run")]})
        return brain

    def test_task_requiring_the_skill_is_pinned(self, single_root, monkeypatch):
        monkeypatch.delenv("BRAIN_DISABLE_SKILL_ROUTING", raising=False)
        brain = self._brain_with_skill(single_root, requires="playwright")
        r = brain_provider.resolve_for_role(brain, "developer", task="t-x")
        assert r["source"] == "skill-pin"
        assert r["command"] == "claude"

    def test_unrelated_task_follows_the_config(self, single_root, monkeypatch):
        """Иначе один скилл с ограниченным списком клиентов уводил бы все
        задачи роли и делал конфигурацию маршрутизации недостижимой."""
        monkeypatch.delenv("BRAIN_DISABLE_SKILL_ROUTING", raising=False)
        brain = self._brain_with_skill(single_root)
        r = brain_provider.resolve_for_role(brain, "developer", task="t-x")
        assert r["source"] == "config"
        assert r["command"] == "opencode run"

    def test_routing_can_be_disabled_by_env(self, single_root, monkeypatch):
        monkeypatch.setenv("BRAIN_DISABLE_SKILL_ROUTING", "1")
        brain = self._brain_with_skill(single_root, requires="playwright")
        assert brain_provider.resolve_for_role(brain, "developer", task="t-x")["source"] == "config"


class TestProfiles:
    """t-2026-08-10-routing-role-coverage: роль указывает профиль, а не список."""

    def _matrix(self, brain: Path) -> None:
        (brain / "config").mkdir(parents=True, exist_ok=True)
        (brain / "config" / "routing.json").write_text(json.dumps({
            "version": brain_provider.MATRIX_VERSION,
            "defaults": {"cli": "claude"},
            "providers": {
                "claude": {"command": "claude", "model_flag": "--model {model}", "enabled": True},
                "opencode": {"command": "opencode run", "model_flag": "-m opencode/{model}", "enabled": True},
                "gemini": {"command": "gemini", "model_flag": "-m {model}", "enabled": False,
                           "note": "отключён оператором"},
            },
            "profiles": {
                "architecture": [{"rank": 1, "provider": "claude", "model": "opus"}],
                "implementation": [{"rank": 1, "provider": "opencode", "model": ""}],
                "independent-review": [
                    {"rank": 1, "provider": "gemini", "model": "pro"},
                    {"rank": 2, "provider": "opencode", "model": "deepseek-v4-pro"},
                ],
            },
            "roles": {
                "architect": {"profile": "architecture"},
                "developer": {"profile": "implementation"},
                "reviewer": {"profile": "independent-review", "diversify_from_author": True},
                "security": {"profile": "independent-review"},
            },
        }, ensure_ascii=False), encoding="utf-8")

    def test_command_is_composed_from_provider_and_model(self, brain):
        self._matrix(brain)
        r = brain_provider.resolve_for_role(brain, "architect")
        assert r["command"] == "claude --model opus"
        assert r["profile"] == "architecture"

    def test_empty_model_leaves_the_bare_command(self, brain):
        self._matrix(brain)
        assert brain_provider.resolve_for_role(brain, "developer")["command"] == "opencode run"

    def test_roles_sharing_a_profile_resolve_alike(self, brain):
        self._matrix(brain)
        a = brain_provider.resolve_for_role(brain, "reviewer")
        b = brain_provider.resolve_for_role(brain, "security")
        assert a["command"] == b["command"] == "opencode run -m opencode/deepseek-v4-pro"

    def test_status_reports_the_profile_for_every_role(self, brain):
        self._matrix(brain)
        status = brain_provider.collect_provider_status(brain)
        assert set(status["roles"]) == {"architect", "developer", "reviewer", "security"}
        assert all(info["profile"] for info in status["roles"].values())
        assert all(info["preferred"] for info in status["roles"].values())

    def test_disabled_provider_shows_up_as_unavailable_with_reason(self, brain):
        self._matrix(brain)
        info = brain_provider.collect_provider_status(brain)["roles"]["reviewer"]
        reasons = [u["reason"] for u in info["unavailable"]]
        assert any("отключён оператором" in r for r in reasons)


def test_every_role_file_has_a_route():
    """Роль без записи молча уходила в CLI_DEFAULT — без модели и без следа."""
    matrix = json.loads((REPO / "config" / "routing.json").read_text(encoding="utf-8"))
    on_disk = {f.stem for f in (REPO / "roles").glob("*.md")}
    missing = sorted(on_disk - set(matrix["roles"]))
    assert not missing, f"роли без профиля: {missing}"
    unknown_profile = sorted(
        role for role, entry in matrix["roles"].items()
        if entry.get("profile") not in matrix["profiles"]
    )
    assert not unknown_profile, f"ссылка на несуществующий профиль: {unknown_profile}"


def test_quota_is_a_fact_not_a_policy():
    """Квота codex истекает по TTL в кэше здоровья, а не выключает провайдера."""
    matrix = json.loads((REPO / "config" / "routing.json").read_text(encoding="utf-8"))
    assert matrix["providers"]["codex"]["enabled"] is True
    assert matrix["providers"]["gemini"]["enabled"] is False
    assert "opencode" in matrix["providers"]


class TestValidateRouting:
    """t-2026-08-10-routing-validate: дыры в маршрутизации видны валидатору."""

    def _brain(self, brain: Path, provider_command: str = "claude") -> Path:
        (brain / "roles").mkdir(parents=True, exist_ok=True)
        (brain / "roles" / "developer.md").write_text("# developer\n", encoding="utf-8")
        (brain / "config").mkdir(parents=True, exist_ok=True)
        (brain / "config" / "routing.json").write_text(json.dumps({
            "version": brain_provider.MATRIX_VERSION,
            "defaults": {"cli": "claude"},
            "providers": {"claude": {"command": provider_command,
                                     "model_flag": "--model {model}", "enabled": True}},
            "profiles": {"universal": [{"rank": 1, "provider": "claude", "model": "sonnet"}]},
            "roles": {"developer": {"profile": "universal"}},
        }, ensure_ascii=False), encoding="utf-8")
        return brain

    def test_clean_config_has_no_issues(self, single_root):
        from brain_wiki.validators import validate_routing

        assert validate_routing(self._brain(single_root)) == []

    def test_missing_executable_is_a_warning_not_an_error(self, single_root):
        """CLI может быть не установлен здесь, но записан для другой машины."""
        from brain_wiki.validators import validate_routing

        issues = validate_routing(self._brain(single_root, provider_command="нет-такой-команды"))
        assert [i.severity for i in issues] == ["WARN"]
        assert "не найдена" in issues[0].message

    def test_health_record_silences_the_warning(self, single_root):
        """Если про кандидата есть запись о здоровье, отсутствие бинаря уже учтено."""
        from brain_wiki.validators import validate_routing

        brain = self._brain(single_root, provider_command="нет-такой-команды")
        (brain / ".provider-health.json").write_text(json.dumps({
            "items": {"claude/sonnet": {"status": "unavailable", "reason": "не установлен",
                                        "checked_at": "2099-01-01T00:00:00Z"}},
        }), encoding="utf-8")
        assert validate_routing(brain) == []

    def test_missing_config_is_an_error_when_roles_exist(self, single_root):
        from brain_wiki.validators import validate_routing

        (single_root / "roles").mkdir()
        (single_root / "roles" / "developer.md").write_text("# developer\n", encoding="utf-8")
        issues = validate_routing(single_root)
        assert any(i.severity == "ERROR" and "нет файла маршрутизации" in i.message for i in issues)


class TestDiversification:
    """t-2026-08-10-routing-diversify: правило диверсификации стало машинным.

    «Рецензент и арбитр — модель другого провайдера» из MEMORY.md исполнялось
    руками и было захардкожено одной строкой для reviewer. Теперь роль помечена
    в конфигурации, а провайдера автора сообщает вызывающий.
    """

    def _matrix(self, brain: Path, reviewer_first: str = "claude") -> None:
        (brain / "config").mkdir(parents=True, exist_ok=True)
        (brain / "config" / "routing.json").write_text(json.dumps({
            "version": brain_provider.MATRIX_VERSION,
            "defaults": {"cli": "claude"},
            "providers": {
                "claude": {"command": "claude", "model_flag": "--model {model}", "enabled": True},
                "opencode": {"command": "opencode run", "model_flag": "-m opencode/{model}", "enabled": True},
            },
            "profiles": {
                "review": [
                    {"rank": 1, "provider": reviewer_first, "model": "opus"},
                    {"rank": 2, "provider": "opencode", "model": "deepseek"},
                ],
                "solo-claude": [{"rank": 1, "provider": "claude", "model": "opus"}],
            },
            "roles": {
                "reviewer": {"profile": "review", "diversify_from_author": True},
                "developer": {"profile": "review"},
                "arbiter": {"profile": "solo-claude", "diversify_from_author": True},
            },
        }, ensure_ascii=False), encoding="utf-8")

    def test_author_provider_is_skipped_for_flagged_role(self, brain):
        self._matrix(brain)
        r = brain_provider.resolve_for_role(brain, "reviewer", author_provider="claude")
        assert r["provider"] == "opencode", r

    def test_role_without_the_flag_ignores_the_author(self, brain):
        """Флаг — часть политики: без него провайдер автора ничего не меняет."""
        self._matrix(brain)
        r = brain_provider.resolve_for_role(brain, "developer", author_provider="claude")
        assert r["provider"] == "claude", r

    def test_no_author_means_no_filtering(self, brain):
        self._matrix(brain)
        r = brain_provider.resolve_for_role(brain, "reviewer")
        assert r["provider"] == "claude", r

    def test_matching_providers_change_nothing_when_they_differ(self, brain):
        """Провайдер автора отличается от первого кандидата — фильтр не нужен."""
        self._matrix(brain)
        r = brain_provider.resolve_for_role(brain, "reviewer", author_provider="opencode")
        assert r["provider"] == "claude", r

    def test_rule_is_relaxed_rather_than_blocking_the_launch(self, brain):
        """Без ревью хуже, чем с ревью у того же провайдера — но с предупреждением."""
        self._matrix(brain)
        r = brain_provider.resolve_for_role(brain, "arbiter", author_provider="claude")
        assert r["command"] == "claude --model opus"
        assert r.get("diversify_relaxed") is True
        assert any("диверсификации отменено" in w for w in r["warnings"])

    def test_explicit_not_provider_still_wins(self, brain):
        self._matrix(brain)
        r = brain_provider.resolve_for_role(
            brain, "reviewer", not_provider="opencode", author_provider="claude")
        assert r["provider"] == "claude", r


class TestDocProjection:
    """t-2026-08-10-routing-doc-projection: проза сверяется с конфигурацией машинно."""

    def _page(self, tmp_path: Path, body: str) -> Path:
        (tmp_path / "wiki").mkdir(parents=True, exist_ok=True)
        page = tmp_path / "wiki" / "decision-llm-stack.md"
        page.write_text(body, encoding="utf-8")
        return page

    def _matrix(self, brain: Path) -> None:
        write_routing(brain, {"developer": {"profile": "impl"}})
        cfg = json.loads((brain / "config" / "routing.json").read_text(encoding="utf-8"))
        cfg["profiles"] = {"impl": [{"rank": 1, "provider": "claude", "model": "opus"}]}
        cfg["providers"] = {"claude": {"command": "claude", "model_flag": "--model {model}", "enabled": True}}
        (brain / "config" / "routing.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    def test_text_outside_markers_is_untouched(self, brain):
        """Человеческий текст — не предмет генерации: его правит человек."""
        self._matrix(brain)
        body = ("# Решение\n\nВводный абзац.\n\n"
                f"{brain_provider.DOC_BEGIN}\nстарое\n{brain_provider.DOC_END}\n\n"
                "## Критерии повышения модели\n\nОстаётся как есть.\n")
        page = self._page(brain, body)
        new, changed = brain_provider.project_routing_doc(brain, page)
        assert changed
        assert "Вводный абзац." in new
        assert "## Критерии повышения модели" in new
        assert "Остаётся как есть." in new
        assert "старое" not in new

    def test_projection_is_idempotent(self, brain):
        self._matrix(brain)
        page = self._page(brain, f"# X\n\n{brain_provider.DOC_BEGIN}\n{brain_provider.DOC_END}\n")
        new, _ = brain_provider.project_routing_doc(brain, page)
        page.write_text(new, encoding="utf-8")
        again, changed = brain_provider.project_routing_doc(brain, page)
        assert not changed and again == new

    def test_rendered_block_names_roles_and_candidates(self, brain):
        self._matrix(brain)
        block = brain_provider.render_routing_doc(brain)
        assert "`developer`" in block and "claude/opus" in block

    def test_drift_is_an_error_for_the_validator(self, brain):
        from brain_wiki.validators import validate_routing

        self._matrix(brain)
        (brain / "roles").mkdir(exist_ok=True)
        (brain / "roles" / "developer.md").write_text("# developer\n", encoding="utf-8")
        self._page(brain, f"# X\n\n{brain_provider.DOC_BEGIN}\nвручную\n{brain_provider.DOC_END}\n")
        issues = validate_routing(brain)
        assert any(i.severity == "ERROR" and "разошёлся" in i.message for i in issues), issues
