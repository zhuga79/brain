"""Общая обвязка периодической команды: аргументы, режимы, установка таймера.

Каждый из четырёх циклов держал свою копию одного и того же: разбор `--brain`,
взаимоисключающая пара `--dry-run/--apply`, `--json`, подкоманда
`install-systemd` и её парсер. Копии разошлись даже в мелочах — `--no-enable`
в двух местах был отдельным флагом, который потом руками гасил `--enable`, а в
третьем нормальным `store_false`.

Обвязка не трогает вывод самих циклов: `spec.run` печатает ровно то, что
печатал раньше. Общим стало только то, что у всех совпадало по смыслу.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from brain_core.paths import brain_path, brain_system_path

from . import systemd

INSTALL_COMMAND = "install-systemd"


@dataclass(frozen=True)
class CycleSpec:
    """Что именно отличает один цикл от другого."""

    name: str
    description: str
    run: Callable[[argparse.Namespace], int]
    unit: Callable[[argparse.Namespace], systemd.UnitSpec]
    install_description: str = ""
    default_agent: str = ""
    # validate-cycle требует явного выбора режима: молчаливый dry-run у команды,
    # которую ставят в таймер, слишком легко принять за applied-прогон.
    mode_required: bool = False
    run_args: Callable[[argparse.ArgumentParser], None] | None = None
    install_args: Callable[[argparse.ArgumentParser], None] | None = None


def resolve_brain(args: argparse.Namespace) -> Path:
    """Корень Brain из аргументов, окружения или умолчания."""
    return brain_path(getattr(args, "brain", None)).resolve()


def service_environment(brain: Path) -> list[tuple[str, str]]:
    """BRAIN_PATH и PYTHONPATH — переменные, общие всем шести юнитам.

    t-2026-08-16-operator-timers-dead-user-serv: все шесть циклов несут
    `#!/usr/bin/env python3` (или запускаются через console-скрипт с тем же
    шебангом). Интерактивно первым в PATH обычно идёт Homebrew python3, и туда
    `setup-brain-v2.sh` кладёт `brain-runtime.pth`. Но systemd user-менеджер
    стартует сервисы с собственным минимальным PATH — он не читает login-shell
    и резолвит `env python3` в системный интерпретатор, где `.pth` никогда не
    ставился. Импорт `brain_app` падает `ModuleNotFoundError`, при этом таймер
    в `systemctl list-timers` выглядит `active`: он исправно стартует сервис,
    просто сервис тут же проваливается с exit-code. Пять таймеров молчали так
    двое суток, пока `brain-status` рапортовал установленное ядро.

    PYTHONPATH здесь не альтернатива пакетированию — t-2026-08-14-package-core
    уже закрыл PYTHONPATH-хаки как костыль для интерактивного CLI (brain-validate
    /brain-task находят brain_core через .pth, без ручного sys.path). Здесь
    другой случай: это декларация окружения самого systemd-юнита, а не обход
    установки ядра. systemd не может увидеть .pth стороннего интерпретатора —
    единственный канал сообщить процессу, где лежит дерево, это Environment=
    в самом юните. Ядро остаётся установлено ровно один раз (.pth/editable);
    PYTHONPATH лишь делает путь к этой установке видимым и в systemd-контексте,
    а не только в интерактивном.

    Альтернативы и почему они отклонены — записаны в
    ref: wiki/log.md, t-2026-08-16-operator-timers-dead-user-serv:
      * `.pth` во ВСЕ site-packages, что найдутся на машине — не решает: набор
        интерпретаторов, которые может резолвнуть `env python3` в разных
        контекстах (login shell, systemd, cron, su -c), заранее не известен и
        меняется при апгрейде дистрибутива/Homebrew; чинили бы каждый раз заново.
      * Прибитый абсолютный путь интерпретатора в шебанге/ExecStart — переживает
        только одну машину: юниты правит одна и та же обвязка на нескольких
        хостах (см. `brain-sync.timer.bak-*` — copy-paste между машинами),
        и абсолютный путь Homebrew на одной из них не существует на другой.
      * Полноценный venv вместо .pth-фолбэка — правильный долгосрочный шаг, но
        меняет сам механизм установки ядра, который t-2026-08-14-package-core
        стабилизировал двое суток назад; переигрывать его сейчас — расширять
        blast radius ровно там, где B4-доктрина просит сузить его.
    """
    system_root = brain_system_path(brain=brain)
    return [
        ("BRAIN_PATH", str(brain)),
        ("PYTHONPATH", str(system_root / "runtime" / "lib")),
    ]


def add_mode_args(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    mode = parser.add_mutually_exclusive_group(required=required)
    mode.add_argument("--dry-run", action="store_true", help="Показать результат, ничего не записывая.")
    mode.add_argument("--apply", action="store_true", help="Записать результат: задачи, отчёты, журнал.")


def build_run_parser(spec: CycleSpec) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=spec.name, description=spec.description)
    parser.add_argument("--brain", default=None, help="Путь к Brain. По умолчанию $BRAIN_PATH или ~/brain.")
    add_mode_args(parser, required=spec.mode_required)
    if spec.default_agent:
        parser.add_argument("--agent", default=spec.default_agent, help="Идентификатор агента в записях цикла.")
    parser.add_argument("--json", action="store_true", help="Машиночитаемый вывод.")
    if spec.run_args:
        spec.run_args(parser)
    return parser


def build_install_parser(spec: CycleSpec) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"{spec.name} {INSTALL_COMMAND}",
        description=spec.install_description or f"Установить пользовательский таймер {spec.name}.",
    )
    parser.add_argument("--brain", default=None, help="Путь к Brain. По умолчанию $BRAIN_PATH или ~/brain.")
    parser.add_argument("--unit-dir", default=systemd.DEFAULT_UNIT_DIR, help="Каталог пользовательских юнитов.")
    parser.add_argument("--enable", dest="enable", action="store_true", help="daemon-reload и enable --now таймера.")
    parser.add_argument("--no-enable", dest="enable", action="store_false", help="Только записать файлы юнитов.")
    parser.add_argument("--json", action="store_true", help="Машиночитаемый вывод.")
    parser.set_defaults(enable=False)
    if spec.default_agent:
        parser.add_argument("--agent", default=spec.default_agent, help="Идентификатор агента для таймера.")
    if spec.install_args:
        spec.install_args(parser)
    return parser


def install(spec: CycleSpec, argv: list[str]) -> int:
    args = build_install_parser(spec).parse_args(argv)
    try:
        unit = spec.unit(args)
    except systemd.UnitNameError as exc:
        print(f"{spec.name}: {exc}", file=sys.stderr)
        return 2
    payload = systemd.install(unit, unit_dir=args.unit_dir, enable=args.enable)
    return systemd.report(payload, json_mode=args.json)


def dispatch(spec: CycleSpec, argv: list[str] | None = None) -> int:
    """Точка входа CLI: подкоманда установки или прогон цикла.

    Подкоманду распознаём по первому слову, а не через add_subparsers: у всех
    четырёх команд прогон — поведение по умолчанию, и `--apply` без подкоманды
    должен работать.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == [INSTALL_COMMAND]:
        return install(spec, argv[1:])
    args = build_run_parser(spec).parse_args(argv)
    if not args.apply:
        args.dry_run = True
    return spec.run(args)
