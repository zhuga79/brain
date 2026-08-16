"""Состояние периодических systemd user-юнитов Brain.

t-2026-08-16-operator-timers-dead-user-serv: пять из шести таймеров падали
`ModuleNotFoundError: No module named 'brain_app'` двое суток подряд, а
`systemctl --user list-timers` и `brain-status` всё это время не сообщали
ничего необычного — `active`, `Core 0.2.0`. Таймер, который исправно
стартует сервис и сервис, который тут же проваливается, снаружи неотличимы
от работающей автоматики без обращения к `journalctl`. Это B4-класс:
сигнал утверждает исправность, которой нет.

Модуль не чинит юниты и не трогает systemd — только читает состояние через
`systemctl --user show` и возвращает структуру, которую `brain-status`
показывает человеку. `runner` внедряется параметром ради тестируемости:
тесты подсовывают фейковый `subprocess.run`, не завися от systemd в песочнице.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any, Callable, Sequence

CommandRunner = Callable[..., "subprocess.CompletedProcess[str]"]

# Единый список шести циклов, сведённых в общую обвязку runner.py/systemd.py
# (см. brain_app.cycles). Порядок — как в очереди тикета.
PERIODIC_UNITS: tuple[str, ...] = (
    "brain-sync",
    "brain-index-refresh",
    "brain-provider-probe",
    "brain-queue-cycle",
    "brain-review-cycle",
    "brain-validate-cycle",
)

_SERVICE_PROPERTIES = (
    "LoadState",
    "ActiveState",
    "SubState",
    "Result",
    "ExecMainStatus",
    "ExecMainStartTimestamp",
    "ExecMainExitTimestamp",
)
_TIMER_PROPERTIES = ("LoadState", "ActiveState", "SubState", "UnitFileState")

_TIMEOUT_SECONDS = 5


def _systemctl_available(*, runner: CommandRunner = subprocess.run) -> bool:
    return shutil.which("systemctl") is not None


def _show(unit: str, properties: Sequence[str], *, runner: CommandRunner) -> dict[str, str] | None:
    """`systemctl --user show <unit> --property=...` разобранный в словарь.

    None — вызов не удался (нет systemctl, нет сессии, таймаут): состояние
    неизвестно, это не то же самое, что «юнит провалился».
    """
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        return None
    cmd = [systemctl, "--user", "show", unit, f"--property={','.join(properties)}"]
    try:
        result = runner(cmd, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    parsed: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            parsed[key] = value
    return parsed


def unit_status(name: str, *, runner: CommandRunner = subprocess.run) -> dict[str, Any]:
    """Состояние одного цикла: установлен ли, провалился ли последний прогон."""
    service = _show(f"{name}.service", _SERVICE_PROPERTIES, runner=runner)
    timer = _show(f"{name}.timer", _TIMER_PROPERTIES, runner=runner)

    if service is None or timer is None:
        return {
            "name": name,
            "known": False,
            "installed": False,
            "healthy": None,
            "failed": False,
            "detail": "systemctl unavailable or --user session not reachable",
        }

    installed = service.get("LoadState") == "loaded" and timer.get("LoadState") == "loaded"
    if not installed:
        return {
            "name": name,
            "known": True,
            "installed": False,
            "healthy": None,
            "failed": False,
            "detail": "unit not installed on this host",
        }

    result = service.get("Result", "")
    active_state = service.get("ActiveState", "")
    # Type=oneshot: успешный прогон уходит в inactive, не в active/running.
    # failed — единственное состояние, которое достоверно значит «упал».
    failed = active_state == "failed" or (result not in ("", "success"))
    timer_enabled = timer.get("UnitFileState") == "enabled"

    return {
        "name": name,
        "known": True,
        "installed": True,
        "timer_enabled": timer_enabled,
        "service_active_state": active_state,
        "service_result": result or "unknown",
        "exit_status": service.get("ExecMainStatus", ""),
        "last_start": service.get("ExecMainStartTimestamp", ""),
        "last_exit": service.get("ExecMainExitTimestamp", ""),
        "failed": failed,
        "healthy": (not failed) and timer_enabled,
    }


def collect_periodic_status(
    units: Sequence[str] = PERIODIC_UNITS, *, runner: CommandRunner = subprocess.run
) -> dict[str, Any]:
    """Сводка по всем периодическим юнитам для `brain-status`."""
    available = _systemctl_available(runner=runner)
    items = [unit_status(name, runner=runner) for name in units]
    failed = [item["name"] for item in items if item.get("failed")]
    unknown = [item["name"] for item in items if item.get("known") is False]
    not_installed = [
        item["name"] for item in items if item.get("known") and not item.get("installed")
    ]
    return {
        "available": available,
        "units": items,
        "failed": failed,
        "failed_count": len(failed),
        "unknown": unknown,
        "not_installed": not_installed,
    }
