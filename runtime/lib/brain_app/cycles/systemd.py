"""Единственная реализация установки systemd-юнитов для команд Brain.

Установка была скопирована в шесть CLI (queue/review/sync/validate/index-refresh/
provider-probe) и разошлась на три диалекта. Расхождение стоило не косметики:

* три копии считали `user_flag = "--user" if os.geteuid() != 0 else ""` и под
  root передавали systemctl пустой аргумент — тот отвечал разбором пустого
  имени юнита вместо работы;
* только `sync` проверял имя юнита перед подстановкой в путь и в командную
  строку systemctl;
* `queue` печатал ошибку установки в stdout, `review` — в stderr, остальные
  полагались на `check=True` и вываливали трейсбек питона;
* три копии писали юнит без `Unit=` в секции `[Timer]`, что верно ровно пока
  имена таймера и сервиса совпадают, и молча ломается при `--unit-name`.

Здесь всё это существует в одном экземпляре и в одной форме.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

# Имя юнита попадает и в путь файла, и в аргумент systemctl. Ограничение взято
# из brain-sync-cycle — единственного места, где проверка была изначально.
UNIT_NAME_RE = re.compile(r"^brain-[A-Za-z0-9_.@-]+$")

DEFAULT_UNIT_DIR = "~/.config/systemd/user"

# Слово, которое systemd прочтёт как есть: без кавычек и без экранирования.
_PLAIN_WORD = re.compile(r"[A-Za-z0-9_.:,=@/+-]+")


class UnitNameError(ValueError):
    """Имя юнита не прошло проверку — подставлять его никуда нельзя."""


def _escape(value: str) -> str:
    """`%` удваиваем всегда: systemd раскрывает спецификаторы и внутри кавычек."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")


def quote_arg(value: str) -> str:
    """Аргумент ExecStart в форме, которую systemd прочтёт как одно слово."""
    escaped = _escape(value)
    return escaped if _PLAIN_WORD.fullmatch(value) else f'"{escaped}"'


def quote_assignment(key: str, value: str) -> str:
    """Присваивание для Environment= — в кавычках целиком.

    Без кавычек systemd обрезает значение по первому пробелу, и `BRAIN_PATH`
    с пробелом в пути молча приезжает в сервис половиной.
    """
    return f'"{_escape(f"{key}={value}")}"'


def resolve_command(name: str) -> Path:
    """Путь к команде, которую вписать в ExecStart.

    Берём то, что запустили (`sys.argv[0]`), а не то, что нашлось в PATH:
    установка из дерева должна ставить юнит на файл дерева, иначе таймер
    незаметно уедет на другую копию.
    """
    argv0 = sys.argv[0] if sys.argv and sys.argv[0] else ""
    if argv0:
        candidate = Path(argv0).expanduser()
        if candidate.exists():
            return candidate.resolve()
    from shutil import which

    found = which(name)
    return Path(found).resolve() if found else Path.home() / ".local" / "bin" / name


@dataclass(frozen=True)
class UnitSpec:
    """Описание пары .service/.timer одной периодической команды."""

    name: str
    service_description: str
    timer_description: str
    command: Path
    exec_args: Sequence[str] = ()
    # Ключи секции [Timer]: OnCalendar, OnUnitActiveSec и прочее расписание.
    timer_options: Sequence[tuple[str, str]] = ()
    # Дополнительные ключи секции [Unit] сервиса: After=, Wants=.
    unit_options: Sequence[tuple[str, str]] = ()
    working_dir: Path | None = None
    environment: Sequence[tuple[str, str]] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not UNIT_NAME_RE.match(self.name):
            raise UnitNameError(
                f"имя юнита должно начинаться с 'brain-' и состоять из букв, цифр, _ . @ -: {self.name!r}"
            )

    @property
    def service_name(self) -> str:
        return f"{self.name}.service"

    @property
    def timer_name(self) -> str:
        return f"{self.name}.timer"


def render_service(spec: UnitSpec) -> str:
    lines = ["[Unit]", f"Description={spec.service_description}"]
    lines += [f"{key}={value}" for key, value in spec.unit_options]
    lines += ["", "[Service]", "Type=oneshot"]
    if spec.working_dir is not None:
        lines.append(f"WorkingDirectory={spec.working_dir}")
    lines += [f"Environment={quote_assignment(key, value)}" for key, value in spec.environment]
    exec_parts = [quote_arg(str(spec.command)), *(quote_arg(str(arg)) for arg in spec.exec_args)]
    lines.append("ExecStart=" + " ".join(exec_parts))
    lines.append("")
    return "\n".join(lines)


def render_timer(spec: UnitSpec) -> str:
    lines = ["[Unit]", f"Description={spec.timer_description}", "", "[Timer]"]
    lines += [f"{key}={value}" for key, value in spec.timer_options]
    # Явная привязка: без неё таймер ищет сервис по своему имени, и любое
    # расхождение имён (--unit-name) даёт таймер, который ничего не запускает.
    lines.append(f"Unit={spec.service_name}")
    lines += ["", "[Install]", "WantedBy=timers.target", ""]
    return "\n".join(lines)


def systemctl_args(*args: str) -> list[str]:
    """Аргументы systemctl с областью, подходящей текущему пользователю."""
    scope = [] if os.geteuid() == 0 else ["--user"]
    return ["systemctl", *scope, *args]


def install(spec: UnitSpec, *, unit_dir: str | os.PathLike[str] | None = None, enable: bool = False) -> dict[str, Any]:
    """Записать юниты и, если просят, включить таймер.

    Возвращает описание сделанного. Неудачу systemctl кладёт в те же данные
    (`error`, `returncode`), а не поднимает исключение: вызывающему CLI нужно
    напечатать её в том же формате, что и успех.
    """
    target = Path(unit_dir or DEFAULT_UNIT_DIR).expanduser()
    target.mkdir(parents=True, exist_ok=True)

    service_path = target / spec.service_name
    timer_path = target / spec.timer_name
    service_path.write_text(render_service(spec), encoding="utf-8")
    timer_path.write_text(render_timer(spec), encoding="utf-8")

    payload: dict[str, Any] = {
        "ok": True,
        "mode": "install-systemd",
        "status": "installed",
        "unit_name": spec.name,
        "unit_dir": str(target),
        "service": str(service_path),
        "timer": str(timer_path),
        "enabled": False,
    }
    if not enable:
        return payload

    for args in (("daemon-reload",), ("enable", "--now", spec.timer_name)):
        result = subprocess.run(systemctl_args(*args), check=False, capture_output=True, text=True)
        if result.returncode != 0:
            payload["ok"] = False
            payload["status"] = "enable-failed"
            payload["returncode"] = result.returncode
            payload["error"] = (result.stderr or result.stdout).strip() or f"systemctl {' '.join(args)} failed"
            return payload
    payload["enabled"] = True
    return payload


def report(payload: dict[str, Any], *, json_mode: bool = False) -> int:
    """Напечатать результат установки. Возвращает код выхода для CLI."""
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif payload.get("error"):
        print(payload["error"], file=sys.stderr)
    else:
        print(f"Systemd units written to: {payload['unit_dir']}")
        print(f"- {payload['service']}")
        print(f"- {payload['timer']}")
        if payload["enabled"]:
            print(f"Enabled and started {payload['unit_name']}.timer")
        else:
            print("To enable, run:")
            print("  systemctl --user daemon-reload")
            print(f"  systemctl --user enable --now {payload['unit_name']}.timer")
    return int(payload.get("returncode") or 0)
