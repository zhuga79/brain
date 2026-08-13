"""Время Brain — одна реализация вместо пяти копий.

Формат меток намеренно один на всю систему: они попадают в блоки задач
(`started:`, `completed:`), в журнал и в имена файлов, и парсятся обратно.
Разъехавшийся формат ломает разбор молча.
"""

from __future__ import annotations

from datetime import datetime, timezone

ISO_Z = "%Y-%m-%dT%H:%M:%SZ"
"""Формат меток времени: UTC, секундная точность, суффикс Z."""


def now() -> datetime:
    """Текущий момент объектом — всегда UTC, не локальные часы.

    Нужен там, где от одного и того же момента берут несколько представлений:
    метку в заголовок, дату в поле, штамп в имя файла. Три отдельных вызова
    utc_now() иногда расходятся на секунду — и отчёт ссылается на файл, которого
    нет. Идентификатор задачи (дата и запасной суффикс) берёт этот момент один
    раз: это расходится с прежним локальным `date +%Y-%m-%d`.
    """
    return datetime.now(timezone.utc)


def utc_now(moment: datetime | None = None) -> str:
    """Время UTC в каноническом формате; без аргумента — текущее."""
    return (moment or now()).strftime(ISO_Z)


def parse(value: str) -> datetime | None:
    """Разобрать метку обратно. None, если формат не тот.

    Терпимо относится к суффиксу +00:00 — так писали более ранние версии.
    """
    text = (value or "").strip()
    if not text:
        return None
    for fmt in (ISO_Z, "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def stamp_for_filename(moment: datetime | None = None) -> str:
    """Метка для имён файлов: без двоеточий, они плохи для путей."""
    return (moment or now()).strftime("%Y-%m-%d-%H%M%SZ")
