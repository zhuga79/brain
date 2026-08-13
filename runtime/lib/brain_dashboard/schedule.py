"""Опрос системных расписаний: cron, пользовательские таймеры systemd, at.

Отделено от сбора данных дашборда по двум причинам. Первая: это единственное
место, где дашборд выходит за пределы своего дерева и запускает внешние
команды, — такую границу лучше видеть отдельным модулем, а не строкой
`subprocess.run` посреди сборки статуса. Вторая: разбор вывода трёх команд —
чистая функция от текста, и проверять её надо на фикстурах, а не на живой
машине, где `atq` может быть не установлен, а таймеров может не быть вовсе.
"""

from __future__ import annotations

import subprocess
from typing import Any, Callable

PROBE_TIMEOUT_SEC = 3

CRON_ENV_PREFIXES = ("SHELL=", "PATH=", "MAILTO=")
TIMER_HEADER_PREFIXES = ("NEXT ", "0 timers", "No timers")
UNSCHEDULED_LABEL = "не запланирован"


def probe(cmd: list[str]) -> dict[str, Any]:
    """Запустить команду опроса. Любой отказ — данные, а не исключение.

    Дашборд показывает расписание как одну из секций: отсутствие `atq` не повод
    ронять страницу целиком, поэтому код возврата и текст ошибки возвращаются
    наравне с успешным выводом.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SEC)
        return {"returncode": result.returncode, "stdout": result.stdout or "", "stderr": result.stderr or ""}
    except FileNotFoundError:
        return {"returncode": 127, "stdout": "", "stderr": "command not found"}
    except subprocess.TimeoutExpired:
        return {"returncode": 124, "stdout": "", "stderr": "timeout"}
    except OSError as exc:
        return {"returncode": 1, "stdout": "", "stderr": str(exc)}


def parse_crontab(text: str) -> list[dict[str, str]]:
    """Строки crontab: пять полей расписания и команда.

    Комментарии и присваивания окружения пропускаем — это не задания.
    """
    items: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(CRON_ENV_PREFIXES):
            continue
        parts = stripped.split(None, 5)
        if len(parts) < 6:
            continue
        items.append({"schedule": " ".join(parts[:5]), "command": parts[5]})
    return items


def parse_systemd_timers(text: str) -> list[dict[str, str]]:
    """Таблица `systemctl list-timers`.

    Колонки не фиксированы по ширине и меняются от версии к версии, поэтому
    опорой служит само имя юнита: всё до него — время следующего запуска,
    следующее слово — активируемый сервис. Заголовок таблицы (`NEXT ...`)
    отбрасывается; строка с `n/a` в колонке NEXT остаётся и помечается
    как «не запланирован».
    """
    items: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(TIMER_HEADER_PREFIXES):
            continue
        parts = stripped.split()
        unit_index = next((i for i, part in enumerate(parts) if part.endswith(".timer")), -1)
        if unit_index == -1:
            continue
        next_value = UNSCHEDULED_LABEL if parts[0] == "n/a" else " ".join(parts[:unit_index])
        items.append({
            "next": next_value,
            "unit": parts[unit_index],
            "activates": parts[unit_index + 1] if unit_index + 1 < len(parts) else "",
        })
    return items


def parse_atq(text: str) -> list[dict[str, str]]:
    """Очередь `atq`: формат строки не стандартизирован, поэтому храним её целиком."""
    items: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if not parts:
            continue
        items.append({"id": parts[0], "raw": stripped})
    return items


def _block(result: dict[str, Any], items: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "status": "ok" if result["returncode"] == 0 else "error",
        "error": (result["stderr"] or "").strip(),
        "items": items,
    }


SOURCES: tuple[tuple[str, list[str], Callable[[str], list[dict[str, str]]]], ...] = (
    ("cron", ["crontab", "-l"], parse_crontab),
    ("systemd_timers", ["systemctl", "--user", "list-timers", "--all", "--no-pager"], parse_systemd_timers),
    ("at", ["atq"], parse_atq),
)


def collect(runner: Callable[[list[str]], dict[str, Any]] = probe) -> dict[str, Any]:
    """Расписания из всех трёх источников.

    `runner` подменяется в тестах: сам разбор проверяется на фикстурах вывода,
    без живых команд.
    """
    blocks: dict[str, Any] = {}
    summary: dict[str, int] = {}
    for name, cmd, parser in SOURCES:
        result = runner(cmd)
        items = parser(result["stdout"]) if result["returncode"] == 0 else []
        summary[name] = len(items)
        blocks[name] = _block(result, items)
    return {"summary": summary, **blocks}
