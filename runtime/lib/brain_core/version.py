"""Версия ядра — одна на установку.

Нужна, чтобы отличить «правка не действует, потому что неверна» от «правка не
действует, потому что исполняется другая копия». До перехода на пакет копий
было три (дерево, ~/.local/lib/brain, ~/.local/share/brain/lib), и разойтись
они могли молча.
"""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

DISTRIBUTION = "brain-runtime"


def core_version() -> str:
    """Версия установленного пакета. `unpackaged`, если установки нет."""
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return "unpackaged"


def core_location() -> str:
    """Каталог, из которого реально загружено ядро."""
    return str(Path(__file__).resolve().parent.parent)
