"""Единственная реализация corrective-задачи: цикл нашёл проблему — она в очереди.

Четыре цикла заводили такие задачи каждый по-своему, и различия были не
стилистическими:

* `validate` и `provider-probe` искали дубликат только в `active.md` — задача,
  закрытая и уехавшая в `done.md`, заводилась заново на каждом прогоне;
* `queue` и `review` смотрели оба файла, но по-разному: первый искал голую
  строку источника, второй — с префиксом `source:`;
* ни один не брал блокировку очереди. Два таймера, сработавшие в одну минуту,
  дописывали `active.md` поверх друг друга, и одна из задач исчезала.

Здесь дедупликация одна (источник и заголовок; active.md всегда,
done.md только в окне 72ч — wiki/decision-corrective-recurrence.md),
запись — под общей блокировкой очереди, и партия задач пишется одним
изменением файла.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import brain_task_parser
from brain_core import atomic, clock, taskfile

DEFAULT_ACCEPTANCE = "Corrective action completed and verified."

# wiki/decision-corrective-recurrence.md — закрытие глушит источник не навсегда.
DONE_SILENCE = timedelta(hours=72)


@dataclass(frozen=True)
class Corrective:
    """Задача, которую цикл предлагает завести по результату прогона."""

    title: str
    source: str
    role: str = "developer"
    priority: str = "P2"
    acceptance: str = DEFAULT_ACCEPTANCE
    mode: str = "solo"
    ref: str = ""
    # Хвост идентификатора. По умолчанию собирается из заголовка; задаётся явно
    # там, где id — часть контракта и не должен меняться вслед за формулировкой.
    slug: str = ""


def slugify(text: str, limit: int = 46) -> str:
    """Часть идентификатора задачи, собранная из заголовка."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug or "cycle")[:limit].strip("-")


def _matches(item: Corrective, text: str) -> bool:
    """Совпадение источника или заголовка в одном куске текста."""
    return f"source: {item.source}" in text or item.title in text


def _completed_at(block: str) -> datetime | None:
    """Штамп completed: из уже выделенного блока, без разбора всего файла."""
    prefix = "completed:"
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return clock.parse(stripped[len(prefix):].strip())
    return None


def already_queued(item: Corrective, active_text: str, done_text: str) -> bool:
    """Такая задача уже есть — в работе или недавно закрыта.

    Проверяем и источник, и заголовок: источник ловит повторный прогон того же
    цикла, заголовок — ту же проблему, заведённую руками или другим циклом.
    active.md блокирует всегда. done.md — только пока самому новому совпавшему
    блоку меньше 72 часов (wiki/decision-corrective-recurrence.md).
    """
    if _matches(item, active_text):
        return True
    newest: datetime | None = None
    for block in brain_task_parser.find_blocks(done_text):
        info = brain_task_parser.parse_block(block)
        if not info:
            continue
        if info.get("title") != item.title and f"source: {item.source}" not in block:
            continue
        completed = _completed_at(block)
        if completed is not None and (newest is None or completed > newest):
            newest = completed
    if newest is None:
        return False
    return clock.now() - newest < DONE_SILENCE


def unique_task_id(corpus: str, base: str) -> str:
    """Идентификатор, которого ещё нет в тексте очереди."""
    candidate = base
    n = 2
    while re.search(rf"\b{re.escape(candidate)}\b", corpus):
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def render(item: Corrective, task_id: str) -> str:
    """Блок задачи в грамматике очереди."""
    lines = [
        f"- [ ] [{item.priority}] {task_id} — {item.title}",
        f"      role: {item.role}   mode: {item.mode}",
        f"      acceptance: {item.acceptance}",
    ]
    if item.ref:
        lines.append(f"      ref: {item.ref}")
    lines.append(f"      source: {item.source}")
    return "\n".join(lines)


def append(brain: Path, items: Iterable[Corrective], *, day: str | None = None) -> list[str]:
    """Дописать в очередь те задачи, которых там ещё нет.

    Возвращает идентификаторы заведённых задач; пропущенные дубликаты в ответе
    не отражаются — вызывающему важно, что появилось, а не что не появилось.
    """
    items = list(items)
    if not items:
        return []

    today = day or clock.utc_now()[:10]
    tasks_dir = brain / "tasks"
    active_path = tasks_dir / "active.md"
    done_path = tasks_dir / "done.md"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    added: list[str] = []
    with taskfile.queue_lock(tasks_dir):
        active_text = atomic.read_text(active_path) or "# Active Tasks\n"
        done_text = atomic.read_text(done_path)

        blocks: list[str] = []
        for item in items:
            if not item.title or already_queued(item, active_text, done_text):
                continue
            # Идентификатор сверяем и с уже собранной партией: две задачи одного
            # прогона с похожими заголовками дают одинаковую основу id.
            corpus = active_text + "\n" + done_text + "\n" + "\n".join(blocks)
            task_id = unique_task_id(corpus, f"t-{today}-{item.slug or slugify(item.title)}")
            blocks.append(render(item, task_id))
            added.append(task_id)

        if blocks:
            body = active_text.rstrip() + "\n\n" + "\n\n".join(blocks) + "\n"
            taskfile.atomic_write(active_path, body)
    return added
