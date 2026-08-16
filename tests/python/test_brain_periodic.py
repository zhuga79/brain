"""t-2026-08-16-operator-timers-dead-user-serv: молчащий таймер обязан быть виден.

Пять из шести периодических юнитов двое суток падали `ModuleNotFoundError`
под systemd, а `systemctl --user list-timers` и `brain-status` показывали
`active`/`Core 0.2.0` — никакого сигнала о провале. Тесты здесь не поднимают
настоящий systemd (в песочнице/CI его может не быть вовсе): `unit_status` и
`collect_periodic_status` принимают `runner` — подставной `subprocess.run`,
который отдаёт заранее собранный вывод `systemctl show`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import pytest

import brain_periodic

REPO = Path(__file__).resolve().parent.parent.parent


class FakeCompleted:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


def _kv(pairs: dict[str, str]) -> str:
    return "\n".join(f"{k}={v}" for k, v in pairs.items()) + "\n"


def make_runner(service: dict[str, str] | None, timer: dict[str, str] | None):
    """Фейковый systemctl: сервис отдаёт `service`, таймер — `timer`.

    None для любой из сторон эмулирует ошибку/недоступность вызова.
    """

    def runner(cmd: Sequence[str], **_kwargs):
        target = cmd[3]  # systemctl --user show <unit> --property=...
        if target.endswith(".service"):
            return FakeCompleted(stdout=_kv(service)) if service is not None else FakeCompleted(returncode=1)
        return FakeCompleted(stdout=_kv(timer)) if timer is not None else FakeCompleted(returncode=1)

    return runner


HEALTHY_SERVICE = {
    "LoadState": "loaded",
    "ActiveState": "inactive",
    "SubState": "dead",
    "Result": "success",
    "ExecMainStatus": "0",
    "ExecMainStartTimestamp": "Sun 2026-08-16 11:00:00 EEST",
    "ExecMainExitTimestamp": "Sun 2026-08-16 11:00:01 EEST",
}
HEALTHY_TIMER = {"LoadState": "loaded", "ActiveState": "active", "SubState": "waiting", "UnitFileState": "enabled"}

# Ровно то, что журналировал оператор: ModuleNotFoundError -> exit 1 -> failed.
BROKEN_SERVICE = {
    "LoadState": "loaded",
    "ActiveState": "failed",
    "SubState": "failed",
    "Result": "exit-code",
    "ExecMainStatus": "1",
    "ExecMainStartTimestamp": "Sun 2026-08-16 10:55:02 EEST",
    "ExecMainExitTimestamp": "Sun 2026-08-16 10:55:02 EEST",
}

NOT_INSTALLED_SERVICE = {"LoadState": "not-found", "ActiveState": "inactive", "Result": "success"}
NOT_INSTALLED_TIMER = {"LoadState": "not-found", "ActiveState": "inactive", "UnitFileState": ""}


def test_healthy_unit_reports_no_failure():
    runner = make_runner(HEALTHY_SERVICE, HEALTHY_TIMER)
    status = brain_periodic.unit_status("brain-sync", runner=runner)
    assert status["installed"] is True
    assert status["failed"] is False
    assert status["healthy"] is True
    assert status["service_result"] == "success"


def test_failed_service_is_flagged_even_though_timer_is_active():
    """Таймер `active` и сервис `failed` — ровно наблюдавшаяся картина."""
    runner = make_runner(BROKEN_SERVICE, HEALTHY_TIMER)
    status = brain_periodic.unit_status("brain-sync", runner=runner)
    assert status["installed"] is True
    assert status["failed"] is True
    assert status["healthy"] is False
    assert status["service_result"] == "exit-code"
    assert status["exit_status"] == "1"


def test_disabled_timer_is_not_healthy_even_if_last_run_succeeded():
    runner = make_runner(HEALTHY_SERVICE, {**HEALTHY_TIMER, "UnitFileState": "disabled"})
    status = brain_periodic.unit_status("brain-sync", runner=runner)
    assert status["failed"] is False
    assert status["healthy"] is False


def test_unit_not_installed_is_not_a_failure():
    runner = make_runner(NOT_INSTALLED_SERVICE, NOT_INSTALLED_TIMER)
    status = brain_periodic.unit_status("brain-sync", runner=runner)
    assert status["installed"] is False
    assert status["failed"] is False
    assert status["healthy"] is None


def test_systemctl_call_failure_is_unknown_not_failed():
    runner = make_runner(None, None)
    status = brain_periodic.unit_status("brain-sync", runner=runner)
    assert status["known"] is False
    assert status["failed"] is False
    assert status["healthy"] is None


def test_systemctl_timeout_is_treated_as_unknown():
    def timeout_runner(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 5))

    status = brain_periodic.unit_status("brain-sync", runner=timeout_runner)
    assert status["known"] is False
    assert status["healthy"] is None


def test_collect_periodic_status_lists_only_the_failed_unit(monkeypatch):
    monkeypatch.setattr(brain_periodic.shutil, "which", lambda _name: "/usr/bin/systemctl")

    def runner(cmd: Sequence[str], **_kwargs):
        unit = cmd[3]
        if unit.startswith("brain-sync"):
            service, timer = BROKEN_SERVICE, HEALTHY_TIMER
        else:
            service, timer = HEALTHY_SERVICE, HEALTHY_TIMER
        return FakeCompleted(stdout=_kv(service if unit.endswith(".service") else timer))

    summary = brain_periodic.collect_periodic_status(runner=runner)
    assert summary["available"] is True
    assert summary["failed"] == ["brain-sync"]
    assert summary["failed_count"] == 1
    assert len(summary["units"]) == len(brain_periodic.PERIODIC_UNITS)


def test_collect_periodic_status_without_systemctl_binary(monkeypatch):
    """Нет systemctl (не Linux / контейнер без systemd) — не ложный провал."""
    monkeypatch.setattr(brain_periodic.shutil, "which", lambda _name: None)
    summary = brain_periodic.collect_periodic_status(runner=subprocess.run)
    assert summary["available"] is False
    assert summary["failed"] == []
    assert all(item["known"] is False for item in summary["units"])


def test_periodic_units_list_matches_the_six_shared_cycles():
    """Состав — те же шесть циклов, что и в brain_app.cycles.runner/systemd."""
    assert set(brain_periodic.PERIODIC_UNITS) == {
        "brain-sync",
        "brain-index-refresh",
        "brain-provider-probe",
        "brain-queue-cycle",
        "brain-review-cycle",
        "brain-validate-cycle",
    }


# ── periodic-секция и досрочно закрытый читатель ────────────────────────────
#
# Секция periodic-юнитов подняла типичный размер `brain-status --json` выше
# 64КБ (объём трубы ядра за один write()). Смок-кейсы вызывают
# `brain-status --json | grep -q '"cli_parity"'`: grep закрывает читающий
# конец, как только находит совпадение в начале вывода, не дожидаясь
# остального. При большом выводе это гонка: если систем-статус ещё не успел
# дописать всё в трубу, следующий write() ловит EPIPE, необработанный
# BrokenPipeError даёт brain-status код возврата 1, и `set -o pipefail`
# красит всю команду — grep нашёл что искал, а продюсер посчитан упавшим.
# 04-wiki-contract так падал дважды подряд в полном прогоне (100 кейсов),
# не воспроизводясь ни изолированно, ни в укороченном прогоне — целиком
# зависело от того, успевает ли запись обогнать закрытие трубы.

def _status_env(tmp_path: Path) -> dict[str, str]:
    brain = tmp_path / "brain"
    for rel in ("wiki", "tasks", "council", "raw"):
        (brain / rel).mkdir(parents=True, exist_ok=True)
    (brain / "tasks" / "active.md").write_text("# Active\n", encoding="utf-8")
    (brain / "tasks" / "done.md").write_text("# Done\n", encoding="utf-8")
    (brain / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    (brain / "wiki" / "log.md").write_text("# Log\n", encoding="utf-8")
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["BRAIN_PATH"] = str(brain)
    # BRAIN_SYSTEM_PATH = настоящий чекаут: cli_parity сравнивает его
    # runtime/bin (~90 команд) с пустым installed_bin песочницы — вывод
    # уверенно переваливает за 64КБ без искусственного раздувания.
    env["BRAIN_SYSTEM_PATH"] = str(REPO)
    env["PYTHONPATH"] = str(REPO / "runtime" / "lib")
    return env


def test_brain_status_json_output_exceeds_one_pipe_buffer(tmp_path):
    """Предпосылка гонки: без большого вывода EPIPE физически не возникает."""
    result = subprocess.run(
        [sys.executable, str(REPO / "runtime" / "bin" / "brain-status"), "--json"],
        env=_status_env(tmp_path), capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert len(result.stdout) > 65536, "тест перестал воспроизводить условие гонки"


def test_brain_status_exits_clean_when_reader_closes_early(tmp_path):
    """grep -q закрывает читающий конец рано — brain-status не должен падать.

    Это регресс-тест ровно на то, что уронило 04-wiki-contract: без
    перехвата BrokenPipeError вокруг main() эта проверка ловит код возврата 1
    надёжно (10 из 10 запусков против исходной версии файла), а не изредка.
    """
    env = _status_env(tmp_path)
    for _ in range(5):
        proc = subprocess.Popen(
            [sys.executable, str(REPO / "runtime" / "bin" / "brain-status"), "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True,
        )
        chunk = proc.stdout.read(80)  # как grep -q '"cli_parity"' — совпадение рядом со стартом
        proc.stdout.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise
        assert chunk, "нечего было прочитать — процесс не успел стартовать"
        assert proc.returncode == 0, proc.stderr.read()


def test_main_guard_catches_broken_pipe_around_entrypoint():
    """Статическая подстраховка: перехват не может незаметно потеряться."""
    text = (REPO / "runtime" / "bin" / "brain-status").read_text(encoding="utf-8")
    tail = text.split('if __name__ == "__main__":', 1)[1]
    assert "except BrokenPipeError" in tail
    assert "raise SystemExit(main())" in tail
