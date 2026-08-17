"""Инвариант «владелец задачи = владелец лока».

t-2026-08-14-launch-watch-loop-safety-stop: в очереди оказались задачи `[~]`
с `by: brain-launch-watch-861998`, чей лок принадлежал `reviewer-tmux-bc20`.
`brain-task release` отвергался обеими сторонами, и лок снимали руками.

Здесь проверяется, что такой переход больше не создаётся (`take` захватывает
лок тем же agent-id) и что уже возникшее расхождение разбирается штатно
(`reconcile_locks`).
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from brain_core import taskfile


ACTIVE = """# Active Tasks

- [ ] [P1] t-lock-take — Open task
      role: developer   mode: solo
      acceptance: ok

- [ ] [P2] t-lock-other — Second open task
      role: developer   mode: solo
      acceptance: ok
"""


@pytest.fixture
def tree(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    active = tasks / "active.md"
    active.write_text(ACTIVE, encoding="utf-8")
    (tasks / "done.md").write_text("# Done Tasks\n", encoding="utf-8")
    return tmp_path, active


def _owner_file(brain: Path, tid: str) -> Path:
    return brain / ".locks" / tid / "owner"


def _lock_owner(brain: Path, tid: str) -> str:
    return _owner_file(brain, tid).read_text(encoding="utf-8").split("|")[0]


class TestTakeClaimsTheLock:
    def test_take_creates_a_lock_under_the_same_agent(self, tree):
        brain, active = tree
        taskfile.take(active, "t-lock-take", "agent-alpha")
        assert _lock_owner(brain, "t-lock-take") == "agent-alpha"
        assert "by: agent-alpha" in active.read_text(encoding="utf-8")

    def test_take_refuses_when_another_agent_holds_the_lock(self, tree):
        brain, active = tree
        taskfile.claim_lock(active, "t-lock-take", "agent-beta")
        before = active.read_bytes()
        with pytest.raises(taskfile.TaskError, match="locked by agent-beta"):
            taskfile.take(active, "t-lock-take", "agent-alpha")
        assert active.read_bytes() == before
        assert _lock_owner(brain, "t-lock-take") == "agent-beta"

    def test_take_reclaims_a_stale_lock(self, tree):
        brain, active = tree
        lock = brain / ".locks" / "t-lock-take"
        lock.mkdir(parents=True)
        (lock / "owner").write_text("dead-agent|1|1\n", encoding="utf-8")
        taskfile.take(active, "t-lock-take", "agent-alpha")
        assert _lock_owner(brain, "t-lock-take") == "agent-alpha"

    def test_repeat_take_restores_a_missing_lock(self, tree):
        brain, active = tree
        taskfile.take(active, "t-lock-take", "agent-alpha")
        # Лок пропал (cleanup, перезапуск) — повторный take восстанавливает его.
        (brain / ".locks" / "t-lock-take" / "owner").unlink()
        (brain / ".locks" / "t-lock-take").rmdir()
        taskfile.take(active, "t-lock-take", "agent-alpha")
        assert _lock_owner(brain, "t-lock-take") == "agent-alpha"

    def test_take_on_missing_task_leaves_no_lock(self, tree):
        brain, active = tree
        with pytest.raises(taskfile.TaskError):
            taskfile.take(active, "t-nonexistent", "agent-alpha")
        assert not (brain / ".locks" / "t-nonexistent").exists()

    def test_release_by_the_taking_agent_works_end_to_end(self, tree):
        _brain, active = tree
        taskfile.take(active, "t-lock-take", "agent-alpha")
        taskfile.release(active, "t-lock-take", "agent-alpha")
        text = active.read_text(encoding="utf-8")
        assert "- [ ] [P1] t-lock-take" in text
        assert "by: agent-alpha" not in text


class TestReconcile:
    def _diverge(self, brain: Path, active: Path) -> None:
        """Воспроизвести состояние инцидента: by: — один агент, лок — другой."""
        taskfile.take(active, "t-lock-take", "watch-861998")
        _owner_file(brain, "t-lock-take").write_text(
            f"reviewer-tmux-bc20|{int(time.time())}|600\n", encoding="utf-8",
        )

    def test_divergence_blocks_both_owners_before_the_fix(self, tree):
        brain, active = tree
        self._diverge(brain, active)
        with pytest.raises(taskfile.TaskError, match="lock owned by reviewer-tmux-bc20"):
            taskfile.release(active, "t-lock-take", "watch-861998")
        with pytest.raises(taskfile.TaskError, match="task owned by watch-861998"):
            taskfile.release(active, "t-lock-take", "reviewer-tmux-bc20")

    def test_reconcile_reports_the_mismatch(self, tree):
        brain, active = tree
        self._diverge(brain, active)
        findings = taskfile.reconcile_locks(active)
        assert [f["kind"] for f in findings] == ["owner_mismatch"]
        assert findings[0]["task_owner"] == "watch-861998"
        assert findings[0]["lock_owner"] == "reviewer-tmux-bc20"
        assert findings[0]["fixed"] is False
        # Отчёт ничего не меняет.
        assert "by: watch-861998" in active.read_text(encoding="utf-8")

    def test_reconcile_fix_returns_the_task_and_drops_the_lock(self, tree):
        brain, active = tree
        self._diverge(brain, active)
        findings = taskfile.reconcile_locks(active, fix=True)
        assert findings[0]["fixed"] is True
        text = active.read_text(encoding="utf-8")
        assert "- [ ] [P1] t-lock-take" in text
        assert "by: watch-861998" not in text
        assert not (brain / ".locks" / "t-lock-take").exists()
        assert taskfile.reconcile_locks(active) == []

    def test_reconcile_restores_a_missing_lock(self, tree):
        brain, active = tree
        taskfile.take(active, "t-lock-take", "agent-alpha")
        _owner_file(brain, "t-lock-take").unlink()
        (brain / ".locks" / "t-lock-take").rmdir()
        findings = taskfile.reconcile_locks(active, fix=True)
        assert [f["kind"] for f in findings] == ["lock_missing"]
        assert _lock_owner(brain, "t-lock-take") == "agent-alpha"
        # Задача остаётся в работе: работа, скорее всего, идёт.
        assert "- [~] [P1] t-lock-take" in active.read_text(encoding="utf-8")

    def test_live_lock_on_an_open_task_is_not_an_orphan(self, tree):
        """t-2026-08-16-reconcile-fix-drops-a-live-loc.

        Прежде эта проверка называлась test_reconcile_drops_an_orphan_lock и
        утверждала обратное: что живой лок на `t-lock-other` (задача остаётся
        `[ ]`, лок только что взят claim_lock, не протух) — это orphan_lock, и
        `--fix` должен его снести. Это было неверно: протокол MEMORY.md прямо
        предписывает сперва `brain-lock acquire`, потом `brain-task take`,
        значит открытая задача под действующим локом — штатное переходное
        окно между этими двумя шагами, а не рассинхрон. `--fix` удалял в этом
        окне живой лок чужого агента — обход владения (класс B2). Теперь
        reconcile это окно распознаёт и не трогает.
        """
        brain, active = tree
        taskfile.claim_lock(active, "t-lock-other", "ghost-agent")
        findings = taskfile.reconcile_locks(active, fix=True)
        assert findings == []
        assert _lock_owner(brain, "t-lock-other") == "ghost-agent"
        assert "- [ ] [P2] t-lock-other" in active.read_text(encoding="utf-8")

    def test_reconcile_drops_a_lock_on_a_nonexistent_task(self, tree):
        """Настоящий orphan: лока владелец существует, а задачи в очереди нет."""
        brain, active = tree
        taskfile.claim_lock(active, "t-ghost-task", "ghost-agent")
        findings = taskfile.reconcile_locks(active, fix=True)
        assert [f["kind"] for f in findings] == ["orphan_lock"]
        assert not (brain / ".locks" / "t-ghost-task").exists()

    def test_reconcile_drops_a_stale_lock_on_an_open_task(self, tree):
        """Протухший лок остаётся orphan, даже если задача открыта: acquire-
        перед-take защищает только ДЕЙСТВУЮЩИЙ лок, не любой лок вообще."""
        brain, active = tree
        taskfile.claim_lock(active, "t-lock-other", "dead-agent")
        _owner_file(brain, "t-lock-other").write_text("dead-agent|1|1\n", encoding="utf-8")
        findings = taskfile.reconcile_locks(active, fix=True)
        assert [f["kind"] for f in findings] == ["orphan_lock"]
        assert not (brain / ".locks" / "t-lock-other").exists()

    def test_reconcile_frees_a_stale_lock(self, tree):
        brain, active = tree
        taskfile.take(active, "t-lock-take", "dead-agent")
        _owner_file(brain, "t-lock-take").write_text("dead-agent|1|1\n", encoding="utf-8")
        findings = taskfile.reconcile_locks(active, fix=True)
        assert [f["kind"] for f in findings] == ["lock_stale"]
        assert "- [ ] [P1] t-lock-take" in active.read_text(encoding="utf-8")
        assert not (brain / ".locks" / "t-lock-take").exists()

    def test_healthy_queue_reports_nothing(self, tree):
        _brain, active = tree
        taskfile.take(active, "t-lock-take", "agent-alpha")
        assert taskfile.reconcile_locks(active) == []
