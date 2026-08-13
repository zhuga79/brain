"""t-2026-08-13-surface: surface возвращается вместе с задачей из очереди.

После e46226f дашборд читает очередь через brain_app.queue.load_active/load_done,
а те идут через brain_tasks.parse_tasks, который ключ `surface` не отдаёт.
В результате render/tasks.py всегда видел "headless": бейдж не показывался,
дефолт запуска вставал в background, счётчики surfaces не различали задачи.

Тест фиксирует контракт: surface вычисляется по единому правилу
brain_task_parser.effective_surface и доходит до дашборда.
"""

from __future__ import annotations

import pytest

import brain_task_parser
from brain_app import queue
from brain_dashboard.collect.tasks import summarize_tasks

ACTIVE = """# Active Tasks

- [ ] [P1] t-lawyer — Юридическая задача
      role: lawyer   mode: solo

- [ ] [P1] t-explicit — Явная интерактивная
      role: developer   mode: solo
      surface: interactive

- [ ] [P1] t-dev — Обычная задача
      role: developer   mode: solo
"""
DONE = """# Done Tasks

- [x] [P1] t-old-lawyer — Закрытая юридическая
      role: lawyer   mode: solo

- [x] [P1] t-old-dev — Закрытая обычная
      role: developer   mode: solo
"""


@pytest.fixture
def brain(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "active.md").write_text(ACTIVE, encoding="utf-8")
    (tasks / "done.md").write_text(DONE, encoding="utf-8")
    return tmp_path


def test_load_active_returns_effective_surface(brain):
    """load_active отдаёт surface, вычисленный как effective_surface.

    Роль lawyer входит в INTERACTIVE_ROLES → interactive; явный surface
    побеждает роль; обычный developer — headless.
    Нормализованная форма не несёт `raw`: исходный блок доступен через
    queue.find() / queue.blocks(), а не дублируется в каждом элементе списка.
    """
    assert "lawyer" in brain_task_parser.INTERACTIVE_ROLES
    by_id = {t["id"]: t for t in queue.load_active(brain)}
    assert by_id["t-lawyer"]["surface"] == "interactive"
    assert by_id["t-explicit"]["surface"] == "interactive"
    assert by_id["t-dev"]["surface"] == "headless"
    assert "raw" not in by_id["t-lawyer"]


def test_load_done_returns_surface_too(brain):
    """load_done отдаёт тот же нормализованный surface.

    Закрытая задача с интерактивной ролью (lawyer) должна вернуться как
    interactive, обычная developer-задача — как headless.
    """
    by_id = {t["id"]: t for t in queue.load_done(brain)}
    assert by_id["t-old-lawyer"]["surface"] == "interactive"
    assert by_id["t-old-dev"]["surface"] == "headless"


def test_summarize_tasks_surfaces_distinguish(brain):
    """Счётчик surfaces в summarize_tasks различает interactive и headless."""
    active = queue.load_active(brain)
    summary = summarize_tasks(active, queue.load_done(brain))
    assert summary["surfaces"]["interactive"] == 2
    assert summary["surfaces"]["headless"] == 1


def test_snapshot_surfaces_distinguish(brain, tmp_path):
    """Снимок дашборда считает interactive и headless раздельно."""
    from brain_dashboard.collect.snapshot import save_snapshot, load_snapshot

    active = queue.load_active(brain)
    done = queue.load_done(brain)
    (tmp_path / "wiki" / "_views").mkdir(parents=True)
    save_snapshot(tmp_path, {
        "tasks": {"active": active, "done": done},
        "locks": {"items": []},
        "council": {"items": []},
    })
    snap = load_snapshot(tmp_path)
    assert snap["surfaces"]["interactive"] == 2
    assert snap["surfaces"]["headless"] == 1


def test_build_html_shows_interactive_badge(brain, tmp_path):
    """Собранная страница показывает бейдж interactive для интерактивной задачи."""
    from brain_dashboard.render.html import build_html

    active = queue.load_active(brain)
    done = queue.load_done(brain)
    brain_dir = tmp_path
    (brain_dir / "wiki").mkdir()
    status = {
        "tasks": {
            "active": active,
            "done": done,
            "summary": summarize_tasks(active, done),
        },
        "providers": {},
        "learning": {"available": False},
        "index": {"status": "none", "health": "ok", "stale": False, "stale_files": []},
        "graph": {"available": False, "nodes": 0, "edges": 0, "node_types": {}, "edge_types": {}},
        "tokens": {"available": False},
        "locks": {"count": 0, "stale_count": 0, "items": []},
        "council": {"count": 0, "items": []},
        "handoff": {"active": False, "counts": {}},
        "handoff_journal": [],
        "scheduled": {
            "summary": {"cron": 0, "systemd_timers": 0, "at": 0},
            "cron": {"status": "error", "error": "no cron", "items": []},
            "systemd_timers": {"status": "ok", "error": "", "items": []},
            "at": {"status": "error", "error": "no at", "items": []},
        },
        "generated_at": "now",
        "brain": str(brain_dir),
    }
    html = build_html(status, brain_dir, "now", False, None, "")

    def card(task_id: str) -> str:
        marker = f"<span class='mono small'>{task_id}</span>"
        at = html.index(marker)
        start = html.rfind("<div class='task-card ", 0, at)
        nxt = html.find("<div class='task-card ", at)
        return html[start:nxt if nxt != -1 else None]

    lawyer = card("t-lawyer")
    assert "interactive" in lawyer
    assert "↗" in lawyer
    assert "value='interactive' selected" in lawyer
    dev = card("t-dev")
    assert "headless" in dev
    assert "value='background' selected" in dev
