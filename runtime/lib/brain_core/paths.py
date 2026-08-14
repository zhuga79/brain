"""Пути Brain — одна реализация вместо четырнадцати копий.

`def brain_path` был скопирован в 14 файлов runtime/bin. Копии не разъезжались
только потому, что тело в одну строку, но любое уточнение — поддержка
symlink'ов, проверка существования, иной источник значения — требовало
четырнадцати одинаковых правок.

Системные ассеты (roles/, teams/, doctrine/, skills/, .cli-mapping.sh)
резолвятся с фолбэком: сначала $BRAIN (локальный оверрайд), затем
$BRAIN_SYSTEM_PATH. Без второй переменной корень один — как раньше.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_DEFAULT_EXPANSION = re.compile(
    r"^\$\{(?P<key>[A-Za-z_][A-Za-z0-9_]*)?:-(?P<default>.*)\}$"
)
_COMMAND_EXPANSION = re.compile(r"\$\(|`")


def operator_env_candidates() -> list[Path]:
    """Где искать корни оператора. Первый существующий файл побеждает."""
    found: list[Path] = []
    override = os.environ.get("BRAIN_ENV_FILE")
    if override:
        found.append(Path(override).expanduser())
    found.append(Path.home() / ".config" / "brain" / "env")
    data = Path(os.environ.get("BRAIN_PATH", str(Path.home() / "brain"))).expanduser()
    found.append(data / ".brain" / "env")
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in found:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def operator_env_file() -> Path:
    """Файл корней оператора: явный override, иначе первый существующий кандидат."""
    override = os.environ.get("BRAIN_ENV_FILE")
    if override:
        return Path(override).expanduser()
    candidates = operator_env_candidates()
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def parse_operator_env(path: Path) -> dict[str, str]:
    """Прочитать KEY=VALUE / export KEY=VALUE. Подстановки $() не исполняются."""
    if path is None or not Path(path).is_file():
        return {}
    parsed: dict[str, str] = {}
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if _COMMAND_EXPANSION.search(value):
            continue
        match = _DEFAULT_EXPANSION.fullmatch(value)
        if match:
            value = match.group("default")
        parsed[key] = _expand_home(value)
    return parsed


def _expand_home(value: str) -> str:
    """Развернуть только $HOME / ${HOME} / ~/ — без произвольных $VAR и $()."""
    home = os.environ.get("HOME") or str(Path.home())
    if value == "~":
        return home
    if value.startswith("~/"):
        value = home + value[1:]
    return value.replace("${HOME}", home).replace("$HOME", home)


def apply_operator_env(path: Path | None = None) -> dict[str, str]:
    """Выставить из файла только пустые/отсутствующие переменные."""
    target = Path(path) if path is not None else operator_env_file()
    applied: dict[str, str] = {}
    for key, value in parse_operator_env(target).items():
        current = os.environ.get(key)
        if current:
            continue
        os.environ[key] = value
        applied[key] = value
    return applied


def _maybe_apply_operator_env() -> None:
    """Подхватить ~/.config/brain/env вне тестов и явного отказа."""
    if os.environ.get("BRAIN_SKIP_OPERATOR_ENV"):
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if os.environ.get("BRAIN_TEST_SANDBOX"):
        return
    apply_operator_env()


def brain_path(value: str | None = None) -> Path:
    """Корень данных Brain: явный аргумент, затем $BRAIN_PATH, затем ~/brain."""
    if not value:
        _maybe_apply_operator_env()
    return Path(value or os.environ.get("BRAIN_PATH", str(Path.home() / "brain"))).expanduser()


def brain_system_path(value: str | None = None, *, brain: Path | None = None) -> Path:
    """Корень системных ассетов: аргумент, затем $BRAIN_SYSTEM_PATH, затем data root."""
    if value:
        return Path(value).expanduser()
    _maybe_apply_operator_env()
    env = os.environ.get("BRAIN_SYSTEM_PATH")
    if env:
        return Path(env).expanduser()
    return brain if brain is not None else brain_path()


def resolve_system_asset(
    rel: str,
    *,
    brain: Path | None = None,
    system: Path | None = None,
) -> Path:
    """Файл системы: локальный оверрайд в $BRAIN, иначе $BRAIN_SYSTEM_PATH."""
    if rel is None or not str(rel).strip():
        raise ValueError("system asset relative path is required")
    clean = str(rel).strip().lstrip("/")
    data = brain if brain is not None else brain_path()
    sysroot = system if system is not None else brain_system_path(brain=data)
    local = data / clean
    if local.exists():
        return local
    return sysroot / clean


def iter_system_files(
    rel_dir: str,
    pattern: str = "*",
    *,
    brain: Path | None = None,
    system: Path | None = None,
) -> list[Path]:
    """Список файлов каталога системы: SYSTEM, затем локальный оверрайд по относительному пути."""
    if rel_dir is None or not str(rel_dir).strip():
        raise ValueError("system asset directory is required")
    data = brain if brain is not None else brain_path()
    sysroot = system if system is not None else brain_system_path(brain=data)
    found: dict[str, Path] = {}
    for root in (sysroot, data):
        base = root / rel_dir
        if not base.is_dir():
            continue
        for path in sorted(base.glob(pattern)):
            if path.is_file():
                found[str(path.relative_to(base))] = path
    return [found[key] for key in sorted(found)]


def system_asset_rel(path: Path, *, brain: Path | None = None) -> str:
    """Относительный путь ассета для сообщений: от data root или system root."""
    data = brain if brain is not None else brain_path()
    for root in (data, brain_system_path(brain=data)):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return path.name


def tasks_dir(brain: Path | None = None) -> Path:
    return brain_path(str(brain) if brain else None) / "tasks"


def active_file(brain: Path | None = None) -> Path:
    return tasks_dir(brain) / "active.md"


def done_file(brain: Path | None = None) -> Path:
    return tasks_dir(brain) / "done.md"


def wiki_dir(brain: Path | None = None) -> Path:
    return brain_path(str(brain) if brain else None) / "wiki"


def log_file(brain: Path | None = None) -> Path:
    return wiki_dir(brain) / "log.md"


def locks_dir(brain: Path | None = None) -> Path:
    return brain_path(str(brain) if brain else None) / ".locks"


def council_dir(brain: Path | None = None) -> Path:
    return brain_path(str(brain) if brain else None) / "council"
