"""t-2026-08-13-utf-8: очередь терпит битый UTF-8, как до e46226f.

Прежний парсер дашборда и brain-shell читали active.md с errors="replace".
queue._read ходит через строгий atomic.read_text — один невалидный байт
роняет collect_status и fallback brain-shell.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

from brain_app import queue
from brain_dashboard.data import collect_status

REPO = Path(__file__).resolve().parents[2]

ACTIVE = (
    "# Active Tasks\n\n"
    "- [ ] [P1] t-ok — Ok\n"
    "      role: developer   mode: solo\n"
).encode("utf-8") + b"\xff"


def _brain(tmp_path: Path) -> Path:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "active.md").write_bytes(ACTIVE)
    (tasks / "done.md").write_text("", encoding="utf-8")
    (tmp_path / "wiki").mkdir()
    return tmp_path


def test_load_active_replaces_invalid_byte(tmp_path):
    brain = _brain(tmp_path)
    tasks = queue.load_active(brain)
    assert [t["id"] for t in tasks] == ["t-ok"]
    text = queue.active_text(brain)
    assert "\ufffd" in text


def test_collect_status_survives_invalid_byte(tmp_path):
    brain = _brain(tmp_path)
    status = collect_status(brain)
    assert [t["id"] for t in status["tasks"]["active"]] == ["t-ok"]


def test_brain_shell_fallback_survives_invalid_byte(tmp_path, capsys):
    """Inline fallback brain-shell читает очередь тем же queue.load_active."""
    brain = _brain(tmp_path)
    loader = importlib.machinery.SourceFileLoader("brain_shell", str(REPO / "runtime" / "bin" / "brain-shell"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    # CLI ходит в живой brain-task; нам нужен inline-fallback на queue.load_active.
    mod._run_cli = lambda args: (1, "", "forced-fallback")
    mod.cmd_tasks(brain)
    out = capsys.readouterr().out
    assert "t-ok" in out
