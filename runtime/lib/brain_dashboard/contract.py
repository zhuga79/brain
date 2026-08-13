"""Что пересекает границу между сбором и рендерингом.

Раньше границы не было: слой рендеринга сам звал сборщиков, а форма данных
нигде не описывалась. Расхождение обнаруживалось единственным способом — KeyError
на собранной странице, то есть уже у человека перед глазами.

Здесь описано только то, что действительно проходит границу, — ключи `status`,
который `collect_status` отдаёт, а `build_html` читает. Типы намеренно
нестрогие внутри (`dict[str, Any]` там, где содержимое разное у каждой секции):
цель — зафиксировать состав, а не переписать весь дашборд на модели.

`total=False` не ставим: отсутствие ключа — это ошибка сборки, и лучше увидеть
её в тесте состава, чем получить пустую секцию на странице.
"""

from __future__ import annotations

from typing import Any, TypedDict


class TasksBlock(TypedDict):
    summary: dict[str, Any]
    active: list[dict[str, Any]]
    done: list[dict[str, Any]]


class LocksBlock(TypedDict):
    count: int
    stale_count: int
    items: list[dict[str, Any]]


class CouncilBlock(TypedDict):
    count: int
    items: list[dict[str, Any]]


class WikiBlock(TypedDict):
    """Страницы вики и адресация Obsidian — для ссылок obsidian://open."""

    pages: list[dict[str, Any]]
    vault: str
    link_prefix: str
    indexed: bool


class Status(TypedDict):
    """Снимок состояния Brain, который читает build_html."""

    brain: str
    tasks: TasksBlock
    locks: LocksBlock
    council: CouncilBlock
    index: dict[str, Any]
    learning: dict[str, Any]
    providers: dict[str, Any]
    tokens: dict[str, Any]
    handoff: dict[str, Any]
    operator: dict[str, Any]
    handoff_journal: list[dict[str, Any]]
    graph: dict[str, Any]
    obsidian_views: dict[str, bool]
    wiki: WikiBlock
    scheduled: dict[str, Any]
    workspaces: dict[str, Any]
    queue_autopilot: dict[str, Any]
    signature: str


STATUS_KEYS = tuple(Status.__annotations__)
"""Состав снимка. Проверяется тестом против того, что реально собирает collect_status."""
