"""t-2026-08-13-131207: хвосты механического рефакторинга сняты осознанно.

parse_tasks в collect/tasks.py — старый парсер дашборда, который умел surface.
После e46226f collect_status ходит через queue.load_active; дубликат осиротел.
Его снимаем, а не подключаем обратно: surface уже в нормализованной форме очереди.
"""

from __future__ import annotations

import ast
import inspect
import itertools
from pathlib import Path

import brain_dashboard.collect.tasks as collect_tasks
from brain_dashboard import data

REPO = Path(__file__).resolve().parents[2]
HTML = REPO / "runtime/lib/brain_dashboard/render/html.py"
DECISION = REPO / "docs/decisions/decision-runtime-core-boundaries.md"


def test_orphan_parse_tasks_removed_from_dashboard_collect():
    """Второй парсер очереди в дашборде снят: очередь читает queue.load_active."""
    assert not hasattr(collect_tasks, "parse_tasks")
    assert "parse_tasks" not in data.__all__
    assert not hasattr(data, "parse_tasks")


def test_html_has_no_blank_run_between_imports_and_build_html():
    source = HTML.read_text(encoding="utf-8")
    tree = ast.parse(source)
    build = next(node for node in tree.body if getattr(node, "name", None) == "build_html")
    last_import = max(
        node.end_lineno
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    )
    gap = source.splitlines()[last_import:build.lineno - 1]
    longest_blank = max(
        (len(list(run)) for blank, run in itertools.groupby(gap, key=lambda line: line.strip() == "") if blank),
        default=0,
    )
    assert longest_blank < 5


def test_decision_does_not_describe_removed_brain_task_next():
    """Страница не выдаёт позиционный ABI удалённого модуля за действующий."""
    text = DECISION.read_text(encoding="utf-8")
    assert "_py brain_task_next" not in text
    assert 'brain_task_next "$A"' not in text
    assert inspect.isfunction(data.collect_status)
