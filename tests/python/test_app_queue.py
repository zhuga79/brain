"""t-2026-08-10-core-queue-facades: контракт очереди в одном экземпляре.

Раньше те же правила были записаны четырежды — в brain-task (bash), MCP,
brain-shell и дашборде — и расходились. Тесты фиксируют сам контракт, а не
конкретный фасад: фасады теперь только зовут этот модуль.
"""

from __future__ import annotations

import json

import pytest

from brain_app import queue

ACTIVE = """# Active Tasks

- [ ] [P1] t-open — Открытая
      role: developer   mode: solo

- [~] [P1] t-work — В работе
      role: linter   mode: solo

- [ ] [P2] t-blocked — Ждёт зависимость
      role: developer   mode: solo
      depends_on: [t-missing]

- [ ] [P2] t-norole — Без роли
      mode: solo
"""
DONE = "- [x] [P1] t-old — Закрытая\n      role: developer\n"


@pytest.fixture
def brain(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "active.md").write_text(ACTIVE, encoding="utf-8")
    (tasks / "done.md").write_text(DONE, encoding="utf-8")
    return tmp_path


# ── чтение ───────────────────────────────────────────────────────────────────

def test_missing_queue_reads_as_empty(tmp_path):
    """Brain без заведённой очереди — штатное состояние, а не отказ."""
    assert queue.load_active(tmp_path) == []
    assert queue.next_task(tmp_path)["task"] is None


def test_empty_role_filter_means_developer(brain):
    """Задача без роли считается задачей developer — так описан формат."""
    ids = [task["id"] for task in queue.filter_tasks(queue.blocks(brain), role="developer")]
    assert ids == ["t-open", "t-blocked", "t-norole"]


def test_role_filter_is_exact_for_other_roles(brain):
    ids = [task["id"] for task in queue.filter_tasks(queue.blocks(brain), role="linter", status="in_progress")]
    assert ids == ["t-work"]


def test_status_all_returns_every_state(brain):
    assert len(queue.filter_tasks(queue.blocks(brain), status="all")) == 4


def test_next_skips_tasks_with_unmet_deps(brain):
    result = queue.next_task(brain, role="developer")
    assert result["task"]["id"] == "t-open"
    assert [item["id"] for item in result["blocked"]] == ["t-blocked"]


def test_find_looks_in_the_archive_too(brain):
    info, raw = queue.find("t-old", brain)
    assert info["id"] == "t-old" and info["state"] == "x"
    assert "Закрытая" in raw


def test_find_missing_returns_none(brain):
    assert queue.find("t-nope", brain) == (None, "")


def test_deps_tree_marks_a_cycle_instead_of_recursing(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "active.md").write_text(
        "- [ ] [P1] t-a — A\n      depends_on: [t-b]\n\n- [ ] [P1] t-b — B\n      depends_on: [t-a]\n",
        encoding="utf-8",
    )
    (tasks / "done.md").write_text("", encoding="utf-8")
    tree = queue.deps_tree("t-a", tmp_path)
    assert tree["deps"][0]["deps"][0]["shown_above"] is True


# ── запись ───────────────────────────────────────────────────────────────────

def test_add_returns_a_free_id(brain):
    first = queue.add("Новая задача", brain)
    second = queue.add("Новая задача", brain)
    assert first != second and second.startswith(first)


def test_add_does_not_reuse_an_archived_id(tmp_path):
    """Занятость проверяется и по done.md: id закрытой задачи брать нельзя."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "active.md").write_text("# Active Tasks\n", encoding="utf-8")
    free = queue.new_task_id("Tema", tmp_path)
    (tasks / "done.md").write_text(f"- [x] [P1] {free} — Tema\n", encoding="utf-8")
    new_id = queue.new_task_id("Tema", tmp_path)
    assert new_id == f"{free}-2"


def test_add_writes_a_parsable_block(brain):
    task_id = queue.add(
        "Со всем", brain, role="architect", mode="council", priority="P0",
        council=["architect", "reviewer"], depends_on=["t-open"], acceptance="готово",
    )
    info, _ = queue.find(task_id, brain)
    assert info["role"] == "architect"
    assert info["mode"] == "council"
    assert info["prio"] == "P0"
    assert info["council"] == ["architect", "reviewer"]
    assert info["deps"] == ["t-open"]
    assert info["acceptance"] == "готово"


def test_add_keeps_existing_tasks(brain):
    before = {task["id"] for task in queue.blocks(brain)}
    queue.add("Ещё одна", brain)
    assert before < {task["id"] for task in queue.blocks(brain)}


def test_take_and_complete_move_the_task(brain):
    queue.take("t-open", "agent-1", brain)
    assert queue.find("t-open", brain)[0]["state"] == "~"
    queue.complete("t-open", "agent-1", "claude-opus-5", brain)
    assert "t-open" not in queue.active_text(brain)
    assert "t-open" in queue.done_text(brain)


def test_block_marks_the_state(brain):
    queue.block("t-open", brain)
    assert queue.find("t-open", brain)[0]["state"] == "!"


@pytest.mark.parametrize(
    "model",
    ["openai-gpt-5.4", "claude-opus-4-8", "gemini-2.5-pro", "grok-4.6"],
)
def test_validate_model_signature_accepts_real_versioned_models(model):
    assert queue.validate_model_signature(model) == model


@pytest.mark.parametrize(
    ("model", "message_part"),
    [
        ("", "real model"),
        ("unsigned", "real model"),
        ("placeholder-summary-text", "real model"),
        ("cleanup", "real model"),
        ("summary", "real model"),
        ("openai-gpt", "numeric version"),
        ("claude-opus", "numeric version"),
        ("bad model 5.4", "format"),
    ],
)
def test_validate_model_signature_rejects_placeholders_and_unversioned_values(model, message_part):
    with pytest.raises(ValueError, match=message_part):
        queue.validate_model_signature(model)


# ── CLI ──────────────────────────────────────────────────────────────────────

def test_cli_named_arguments_replace_the_positional_abi(brain, capsys):
    """Прежний ABI был позиционным на семь мест; порядок путался молча."""
    assert queue.main(["--brain", str(brain), "list", "--role", "linter", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["tasks"] == []


def test_cli_show_missing_task_exits_nonzero(brain, capsys):
    assert queue.main(["--brain", str(brain), "show", "t-nope", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_cli_add_prints_the_id(brain, capsys):
    assert queue.main(["--brain", str(brain), "add", "Через CLI", "--role", "pm"]) == 0
    task_id = capsys.readouterr().out.strip()
    assert queue.find(task_id, brain)[0]["role"] == "pm"
