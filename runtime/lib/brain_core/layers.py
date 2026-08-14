"""Границы слоёв Brain: данные и система.

Разница операционная, а не эстетическая. Слой данных агент меняет постоянно и
по своей работе — очередь, журнал, страницы wiki, материалы дела. Системный
слой описывает, КАК агент работает: роли, доктрины, команды, код рантайма. Его
правка меняет поведение всех будущих запусков, поэтому она требует ревью
человеком.

До разделения автокоммит стажировал roles/, doctrine/, teams/ и MEMORY.md
вместе с очередью: правка системы уезжала в коммит с сообщением
«автозаписи журнала» и терялась. После раздела репозиториев тот же механизм
писал бы такие правки прямо в публичный репозиторий без ревью.
"""

from __future__ import annotations

import os

DATA_PATHS = (
    "tasks/",
    "wiki/",
    "council/",
    "raw/",
    "prd/",
)
"""Слой данных: агент меняет его по ходу работы, автокоммит допустим."""

SYSTEM_PATHS = (
    "roles/",
    "teams/",
    "doctrine/",
    "skills/",
    "runtime/",
    "config/",
    "tests/",
    "MEMORY.md",
    "AGENTS.md",
    "GEMINI.md",
    "brain-spec.md",
    "pyproject.toml",
)
"""Системный слой: меняет поведение будущих запусков, нужен человеческий обзор."""


def is_system_path(path: str) -> bool:
    """Относится ли путь к системному слою.

    Сравнение по префиксу: `roles/lawyer.md` — система, `wiki/roles.md` — нет.
    """
    clean = path.strip().lstrip("./")
    for prefix in SYSTEM_PATHS:
        if prefix.endswith("/"):
            if clean.startswith(prefix):
                return True
        elif clean == prefix:
            return True
    return False


def system_paths_among(paths: list[str]) -> list[str]:
    """Системные пути из списка, в исходном порядке и без повторов."""
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        if path and is_system_path(path) and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def agent_branch(task_id: str) -> str:
    """Ветка, в которой агент правит систему.

    Имя привязано к задаче: обзор идёт по задаче, а не по агенту, и одна и та
    же задача, подхваченная другим агентом, продолжается в той же ветке.
    """
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in task_id.strip())
    return f"agent/{safe or 'unscoped'}"


WRITE_PATH_PREFIXES = (
    "runtime/",
    "roles/",
    "tests/",
    "spec/",
    "docs/",
    "teams/",
    "doctrine/",
    "skills/",
    "config/",
)
"""Системные пути, которые коммитятся только в публичном чекауте."""


def _as_text(value: object) -> str:
    if value is None or isinstance(value, (bytes, bytearray, dict, list, tuple, set)):
        return ""
    if hasattr(value, "__fspath__"):
        value = os.fspath(value)
    if not isinstance(value, str):
        return ""
    return value.strip()


def is_write_path(path: object) -> bool:
    """Путь, который нельзя коммитить в дереве данных при двух корнях."""
    clean = _as_text(path).lstrip("./")
    if not clean:
        return False
    for prefix in WRITE_PATH_PREFIXES:
        if prefix.endswith("/"):
            if clean.startswith(prefix):
                return True
        elif clean == prefix:
            return True
    return False


def write_path_among(paths: list[object] | None) -> list[str]:
    """Write-path файлы из списка, в исходном порядке и без повторов."""
    if not paths:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        text = _as_text(path)
        if text and is_write_path(text) and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def same_tree(left: object, right: object) -> bool:
    """Один и тот же корень, с раскрытием ~ и symlink."""
    from pathlib import Path

    a = _as_text(left)
    b = _as_text(right)
    if not a or not b:
        return False
    try:
        return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()
    except OSError:
        return Path(a).expanduser() == Path(b).expanduser()


def is_data_repo_write(
    *,
    repo: object = None,
    data: object = None,
    system: object = None,
) -> bool:
    """Текущий репозиторий — слой данных, а система живёт в другом корне."""
    if not _as_text(repo) or not _as_text(data) or not _as_text(system):
        return False
    if same_tree(data, system):
        return False
    return same_tree(repo, data)


def write_path_violations(
    paths: list[object] | None,
    *,
    repo: object = None,
    data: object = None,
    system: object = None,
) -> list[str]:
    """Staged system files in the data repo when roots are split."""
    if not is_data_repo_write(repo=repo, data=data, system=system):
        return []
    return write_path_among(paths)
