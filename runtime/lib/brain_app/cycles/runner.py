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

from brain_core.paths import brain_path

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
