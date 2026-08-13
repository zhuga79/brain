"""t-2026-06-26-orchestrator-route: headless auto-next must skip interactive tasks."""
import json

from brain_app import queue

ACTIVE = """# Active

- [ ] [P1] t-inter — Interactive one
      role: developer
      surface: interactive
      gate: approval

- [ ] [P1] t-head — Headless one
      role: developer
"""
DONE = "# Done\n"


def _brain(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "active.md").write_text(ACTIVE, encoding="utf-8")
    (tasks / "done.md").write_text(DONE, encoding="utf-8")
    return tmp_path


def test_headless_filter_skips_interactive(tmp_path, capsys):
    queue.main(["--brain", str(_brain(tmp_path)), "next", "--surface", "headless", "--json"])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is True
    assert out["task"]["id"] == "t-head"


def test_interactive_filter_selects_interactive(tmp_path, capsys):
    queue.main(["--brain", str(_brain(tmp_path)), "next", "--surface", "interactive", "--json"])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["task"]["id"] == "t-inter"
    assert out["task"]["gate"] == "approval"


def test_unfiltered_next_returns_the_top_task(tmp_path, capsys):
    queue.main(["--brain", str(_brain(tmp_path)), "next", "--json"])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["task"]["id"] == "t-inter"


def test_next_is_callable_without_the_cli(tmp_path):
    """Библиотечный вызов — тот же контракт, что и у CLI."""
    result = queue.next_task(_brain(tmp_path), surface="headless")
    assert result["task"]["id"] == "t-head"
    assert result["blocked"] == []
