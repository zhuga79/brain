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
