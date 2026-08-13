"""Пути Brain — одна реализация вместо четырнадцати копий.

`def brain_path` был скопирован в 14 файлов runtime/bin. Копии не разъезжались
только потому, что тело в одну строку, но любое уточнение — поддержка
symlink'ов, проверка существования, иной источник значения — требовало
четырнадцати одинаковых правок.
"""

from __future__ import annotations

import os
from pathlib import Path


def brain_path(value: str | None = None) -> Path:
    """Корень Brain: явный аргумент, затем $BRAIN_PATH, затем ~/brain."""
    return Path(value or os.environ.get("BRAIN_PATH", str(Path.home() / "brain"))).expanduser()


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
