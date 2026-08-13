"""t-2026-08-13-utc: дата id и запасной суффикс — из одного UTC-момента.

Прежний bash брал `date +%Y-%m-%d` (локальный день). new_task_id берёт UTC.
В UTC+3 с полуночи до трёх задача получает вчерашнюю UTC-дату — это сознательный
выбор, а не смесь UTC-даты и локального суффикса.
"""

from __future__ import annotations

from datetime import datetime, timezone

from brain_app import queue
from brain_core import clock


def _empty_brain(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "active.md").write_text("# Active Tasks\n", encoding="utf-8")
    (tasks / "done.md").write_text("", encoding="utf-8")
    return tmp_path


def test_new_task_id_date_and_suffix_share_one_moment(tmp_path, monkeypatch):
    """Два вызова часов, пересекающих полночь UTC, не должны дать сборную дату."""
    moments = iter((
        datetime(2026, 8, 12, 23, 59, 59, tzinfo=timezone.utc),
        datetime(2026, 8, 13, 0, 0, 1, tzinfo=timezone.utc),
    ))
    monkeypatch.setattr(clock, "now", lambda: next(moments))
    brain = _empty_brain(tmp_path)
    tid = queue.new_task_id("???", brain)
    assert tid == "t-2026-08-12-235959"


def test_new_task_id_uses_utc_before_local_midnight_utc_plus_3(tmp_path, monkeypatch):
    """01:30 в UTC+3 — ещё 12-е по UTC; id несёт UTC-дату, не локальную."""
    moment = datetime(2026, 8, 12, 22, 30, 45, tzinfo=timezone.utc)  # 01:30 UTC+3
    monkeypatch.setattr(clock, "now", lambda: moment)
    brain = _empty_brain(tmp_path)
    tid = queue.new_task_id("???", brain)
    assert tid == "t-2026-08-12-223045"
    assert not tid.startswith("t-2026-08-13-")
