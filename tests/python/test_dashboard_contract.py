"""t-2026-08-12-dash-contract: граница между сбором и рендерингом.

До этой задачи границы не было: слой рендеринга сам звал сборщиков и сам читал
диск. Тесты фиксируют три вещи — состав снимка совпадает с описанным,
рендеринг ничего не собирает, и подписи состояний живут на стороне оформления.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from brain_dashboard import contract, data

RENDER_DIR = Path(__file__).resolve().parents[2] / "runtime/lib/brain_dashboard/render"


@pytest.fixture
def brain(tmp_path):
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "active.md").write_text("# Active Tasks\n", encoding="utf-8")
    (tmp_path / "tasks" / "done.md").write_text("# Done\n", encoding="utf-8")
    (tmp_path / "wiki").mkdir()
    return tmp_path


def test_status_has_exactly_the_declared_keys(brain):
    """Состав снимка — часть контракта: лишний ключ так же плох, как забытый."""
    status = data.collect_status(brain)
    assert sorted(status) == sorted(contract.STATUS_KEYS)


def test_wiki_block_shape(brain):
    wiki = data.collect_status(brain)["wiki"]
    assert sorted(wiki) == sorted(contract.WikiBlock.__annotations__)
    assert wiki["indexed"] is False and wiki["pages"] == []


def test_tasks_block_shape(brain):
    tasks = data.collect_status(brain)["tasks"]
    assert sorted(tasks) == sorted(contract.TasksBlock.__annotations__)


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


@pytest.mark.parametrize("path", sorted(RENDER_DIR.rglob("*.py")), ids=lambda p: p.name)
def test_render_does_not_reach_into_the_collection_layer(path):
    """Рендеринг получает данные аргументом и не ходит за ними сам."""
    forbidden = {"brain_index", "brain_provider", "brain_workspace"}
    reached = {name for name in _imports(path) if name.split(".")[0] in forbidden}
    assert reached == set()
    assert not any(name.endswith("data") or ".collect" in name for name in _imports(path))


def test_state_labels_belong_to_the_render_layer():
    """Подпись состояния — решение оформления, а не свойство собранных данных."""
    from brain_dashboard.render.labels import STATE_CLASS, STATE_LABELS

    assert STATE_LABELS[" "] == "open"
    assert STATE_CLASS["~"] == "state-progress"
    assert not hasattr(data, "STATE_LABELS")
