from __future__ import annotations

import time
from pathlib import Path

import pytest

from brain_core import taskfile


ACTIVE = """# Active Tasks

- [~] [P1] t-owner-guard — Owned task
      role: developer   mode: solo
      acceptance: ok
      started: 2026-08-14T00:00:00Z
      by: owner-agent
"""

OPEN_ACTIVE = """# Active Tasks

- [ ] [P1] t-owner-guard — Open task
      role: developer   mode: solo
      acceptance: ok
"""


def _build_queue(tmp_path: Path, active_text: str, *, lock_owner: str | None):
    tasks = tmp_path / "tasks"
    tasks.mkdir(parents=True)
    active = tasks / "active.md"
    done = tasks / "done.md"
    active.write_text(active_text, encoding="utf-8")
    done.write_text("# Done Tasks\n", encoding="utf-8")
    if lock_owner is None:
        return tmp_path, active, done, tmp_path / ".locks" / "t-owner-guard" / "owner"
    locks = tmp_path / ".locks" / "t-owner-guard"
    locks.mkdir(parents=True)
    (locks / "owner").write_text(lock_owner, encoding="utf-8")
    return tmp_path, active, done, locks / "owner"


@pytest.fixture
def queue(tmp_path: Path):
    return _build_queue(tmp_path, ACTIVE, lock_owner=f"owner-agent|{int(time.time())}|600\n")


@pytest.fixture
def open_queue(tmp_path: Path):
    """Открытая задача под живым локом: `[ ]` в очереди + `.locks/<id>/owner`.

    Ровно та расстановка, из-за которой заведён тикет: `acquire` уже прошёл,
    `take` ещё нет, и до правки закрыть такую задачу мог кто угодно.
    """
    return _build_queue(tmp_path, OPEN_ACTIVE, lock_owner=f"owner-agent|{int(time.time())}|600\n")


def _snapshot(*paths: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in paths}


def _assert_same(snapshot: dict[Path, bytes]) -> None:
    for path, before in snapshot.items():
        assert path.read_bytes() == before, path


def test_release_rejects_wrong_owner_before_write(queue):
    _brain, active, done, owner = queue
    before = _snapshot(active, done, owner)
    with pytest.raises(taskfile.TaskError, match="task owned by owner-agent, not intruder"):
        taskfile.release(active, "t-owner-guard", "intruder")
    _assert_same(before)


def test_block_rejects_wrong_owner_before_write(queue):
    _brain, active, done, owner = queue
    before = _snapshot(active, done, owner)
    with pytest.raises(taskfile.TaskError, match="task owned by owner-agent, not intruder"):
        taskfile.block(active, "t-owner-guard", "intruder")
    _assert_same(before)


def test_complete_rejects_wrong_owner_before_write(queue):
    _brain, active, done, owner = queue
    before = _snapshot(active, done, owner)
    with pytest.raises(taskfile.TaskError, match="task owned by owner-agent, not intruder"):
        taskfile.complete(active, done, "t-owner-guard", "intruder", "evil-model")
    _assert_same(before)


def test_complete_rejects_stale_lock_before_write(queue):
    _brain, active, done, owner = queue
    owner.write_text("owner-agent|1|1\n", encoding="utf-8")
    before = _snapshot(active, done, owner)
    with pytest.raises(taskfile.TaskError, match="task lock is stale: t-owner-guard"):
        taskfile.complete(active, done, "t-owner-guard", "owner-agent", "good-model")
    _assert_same(before)


def test_owner_happy_path_mutates_only_active_and_done(queue):
    _brain, active, done, owner = queue
    owner_before = owner.read_bytes()
    taskfile.complete(active, done, "t-owner-guard", "owner-agent", "good-model")
    assert "t-owner-guard" not in active.read_text(encoding="utf-8")
    done_text = done.read_text(encoding="utf-8")
    assert "t-owner-guard" in done_text
    assert "model: good-model" in done_text
    assert owner.read_bytes() == owner_before


# ── открытая задача под локом ────────────────────────────────────────────────
#
# t-2026-08-14-completion-open-lock-ownership: `complete` сверял владельца
# только у задач в состоянии `[~]`. Между `brain-lock acquire` и `brain-task
# take` задача остаётся `[ ]`, и в этом окне её мог закрыть посторонний агент —
# лок был, но на пути завершения его никто не читал.


def test_complete_rejects_intruder_on_open_task_under_live_lock(open_queue):
    _brain, active, done, owner = open_queue
    before = _snapshot(active, done, owner)
    with pytest.raises(taskfile.TaskError, match="lock owned by owner-agent, not intruder"):
        taskfile.complete(active, done, "t-owner-guard", "intruder", "evil-model")
    _assert_same(before)
    assert not taskfile.complete_journal_path(active.parent, "t-owner-guard").exists()


def test_complete_rejects_anonymous_agent_on_open_task_under_live_lock(open_queue):
    _brain, active, done, owner = open_queue
    before = _snapshot(active, done, owner)
    with pytest.raises(taskfile.TaskError, match="task owner required: t-owner-guard"):
        taskfile.complete(active, done, "t-owner-guard", "", "evil-model")
    _assert_same(before)
    assert not taskfile.complete_journal_path(active.parent, "t-owner-guard").exists()


def test_complete_open_task_rejection_is_identical_to_in_progress(tmp_path: Path):
    """Отказ не зависит от состояния задачи: одно сообщение на оба случая.

    Иначе состояние задачи читается по тексту ошибки, а сам отказ выглядит для
    вызывающего как две разные неисправности.
    """
    stamp = f"owner-agent|{int(time.time())}|600\n"
    owned = ACTIVE.replace("by: owner-agent", "by: intruder")
    _b1, active_open, done_open, _o1 = _build_queue(tmp_path / "open", OPEN_ACTIVE, lock_owner=stamp)
    _b2, active_wip, done_wip, _o2 = _build_queue(tmp_path / "wip", owned, lock_owner=stamp)

    messages = []
    for active, done in ((active_open, done_open), (active_wip, done_wip)):
        with pytest.raises(taskfile.TaskError) as excinfo:
            taskfile.complete(active, done, "t-owner-guard", "intruder", "evil-model")
        messages.append(str(excinfo.value))
    assert messages[0] == messages[1] == "lock owned by owner-agent, not intruder"


def test_complete_allows_lock_owner_on_open_task(open_queue):
    _brain, active, done, owner = open_queue
    owner_before = owner.read_bytes()
    taskfile.complete(active, done, "t-owner-guard", "owner-agent", "good-model")
    assert "t-owner-guard" not in active.read_text(encoding="utf-8")
    assert "model: good-model" in done.read_text(encoding="utf-8")
    assert owner.read_bytes() == owner_before


def test_complete_open_task_without_lock_stays_open_to_any_agent(tmp_path: Path):
    """Legacy-путь: лока нет вообще — прямое завершение по-прежнему разрешено.

    Так закрываются задачи, которые никто не брал: `brain-task complete` без
    предшествующего `acquire`.
    """
    _brain, active, done, _owner = _build_queue(tmp_path, OPEN_ACTIVE, lock_owner=None)
    taskfile.complete(active, done, "t-owner-guard", "passerby", "good-model")
    assert "t-owner-guard" not in active.read_text(encoding="utf-8")
    assert "by: passerby" in done.read_text(encoding="utf-8")


def test_complete_in_progress_task_without_lock_stays_owner_only(tmp_path: Path):
    """Legacy-путь для `[~]`: сверяется `by:`, отсутствие лока не отменяет проверку."""
    _brain, active, done, _owner = _build_queue(tmp_path, ACTIVE, lock_owner=None)
    with pytest.raises(taskfile.TaskError, match="task owned by owner-agent, not intruder"):
        taskfile.complete(active, done, "t-owner-guard", "intruder", "evil-model")
    taskfile.complete(active, done, "t-owner-guard", "owner-agent", "good-model")
    assert "t-owner-guard" not in active.read_text(encoding="utf-8")


def test_complete_open_task_with_stale_lock_is_not_blocked(tmp_path: Path):
    """Протухший лок не держит задачу: он перехватываем, значит и не запрещает.

    Тот же протокол, что у `brain-lock acquire` и `claim_lock`, — иначе брошенный
    лок мёртвого агента навсегда закрывал бы путь завершения.
    """
    _brain, active, done, owner = _build_queue(tmp_path, OPEN_ACTIVE, lock_owner="dead-agent|1|1\n")
    taskfile.complete(active, done, "t-owner-guard", "next-agent", "good-model")
    assert "t-owner-guard" not in active.read_text(encoding="utf-8")
    assert "by: next-agent" in done.read_text(encoding="utf-8")
    assert owner.read_bytes() == b"dead-agent|1|1\n"


def test_complete_open_task_with_corrupt_lock_is_not_blocked(tmp_path: Path):
    """Нечитаемый owner-файл — обрывок, а не лок: `claim_lock` его перезаписывает."""
    _brain, active, done, _owner = _build_queue(tmp_path, OPEN_ACTIVE, lock_owner="garbage\n")
    taskfile.complete(active, done, "t-owner-guard", "next-agent", "good-model")
    assert "t-owner-guard" not in active.read_text(encoding="utf-8")


def test_complete_open_task_with_empty_lock_dir_is_not_blocked(tmp_path: Path):
    """Каталог лока без owner-файла — тоже обрывок предыдущего запуска."""
    _brain, active, done, _owner = _build_queue(tmp_path, OPEN_ACTIVE, lock_owner=None)
    (tmp_path / ".locks" / "t-owner-guard").mkdir(parents=True)
    taskfile.complete(active, done, "t-owner-guard", "next-agent", "good-model")
    assert "t-owner-guard" not in active.read_text(encoding="utf-8")


# ── recovery по журналу ──────────────────────────────────────────────────────
#
# Журнал complete переживает падение процесса, и повторный вызов дописывает
# незавершённый переход. Владельца он обязан сверять по тем же правилам, иначе
# запрет на прямое завершение обходится через recovery.


def _write_journal(active: Path, tid: str, owner: str, model: str) -> Path:
    """Журнал незавершённого complete для текущего блока задачи."""
    block = taskfile._any_state_pattern(tid).search(active.read_text(encoding="utf-8"))
    assert block
    source = block.group(0)
    completed = "2026-08-14T00:00:00Z"
    entry = taskfile._build_done_entry(source, owner, model, completed)
    journal = taskfile.complete_journal_path(active.parent, tid)
    taskfile.atomic.write_json(journal, {
        "version": taskfile.COMPLETE_JOURNAL_VERSION,
        "task_id": tid,
        "owner": owner,
        "model": model,
        "model_signature": taskfile._sha256_text(model),
        "completed": completed,
        "source_active": source,
        "source_active_fingerprint": taskfile._active_block_fingerprint(source),
        "final_entry_fingerprint": taskfile._entry_fingerprint(entry),
    })
    return journal


def test_recovery_of_open_task_rejects_intruder_under_live_lock(open_queue):
    _brain, active, done, owner = open_queue
    journal = _write_journal(active, "t-owner-guard", "intruder", "evil-model")
    before = _snapshot(active, done, owner, journal)
    with pytest.raises(taskfile.TaskError, match="lock owned by owner-agent, not intruder"):
        taskfile.complete(active, done, "t-owner-guard", "intruder", "evil-model")
    _assert_same(before)


def test_recovery_of_open_task_allows_lock_owner(open_queue):
    _brain, active, done, owner = open_queue
    journal = _write_journal(active, "t-owner-guard", "owner-agent", "good-model")
    owner_before = owner.read_bytes()
    taskfile.complete(active, done, "t-owner-guard", "owner-agent", "good-model")
    assert "t-owner-guard" not in active.read_text(encoding="utf-8")
    assert "model: good-model" in done.read_text(encoding="utf-8")
    assert not journal.exists()
    assert owner.read_bytes() == owner_before


def test_recovery_of_open_task_with_stale_lock_is_not_blocked(tmp_path: Path):
    """Протухший лок не держит и recovery: правило одно на оба пути."""
    _brain, active, done, _owner = _build_queue(tmp_path, OPEN_ACTIVE, lock_owner="dead-agent|1|1\n")
    journal = _write_journal(active, "t-owner-guard", "next-agent", "good-model")
    taskfile.complete(active, done, "t-owner-guard", "next-agent", "good-model")
    assert "t-owner-guard" not in active.read_text(encoding="utf-8")
    assert "by: next-agent" in done.read_text(encoding="utf-8")
    assert not journal.exists()
