from __future__ import annotations

import threading
import time
from pathlib import Path

from brain_app import queue
from brain_core import prdfile


PRD = """---
id: t-parent
status: draft
---
## Subtasks

- [ ] [P1] s1 — First
      role: developer
      acceptance: ok

- [ ] [P2] s2 — Second
      role: developer
      acceptance: ok
      depends_on: [s1]
"""


def _setup_brain(tmp_path: Path) -> tuple[Path, Path, Path]:
    tasks = tmp_path / "tasks"
    prd = tmp_path / "prd"
    locks = tmp_path / ".locks"
    tasks.mkdir()
    prd.mkdir()
    locks.mkdir()
    active = tasks / "active.md"
    done = tasks / "done.md"
    active.write_text(
        "# Active tasks\n\n"
        "- [~] [P1] t-live — Live work\n"
        "      role: developer   mode: solo\n"
        "      acceptance: ok\n"
        "      started: 2026-08-14T00:00:00Z\n"
        "      by: owner-agent\n",
        encoding="utf-8",
    )
    done.write_text("# Done tasks\n", encoding="utf-8")
    owner = locks / "t-live"
    owner.mkdir(parents=True)
    (owner / "owner").write_text(f"owner-agent|{int(time.time())}|600\n", encoding="utf-8")
    prd_path = prd / "t-parent.md"
    prd_path.write_text(PRD, encoding="utf-8")
    return prd_path, active, done


def test_commit_is_idempotent_when_queue_already_contains_subtasks(tmp_path: Path):
    prd_path, active, done = _setup_brain(tmp_path)
    first = prdfile.commit(prd_path, active, done, "t-parent")
    second = prdfile.commit(prd_path, active, done, "t-parent")

    assert first.appended_ids == ["t-parent-s1", "t-parent-s2"]
    assert second.appended_ids == []
    active_text = active.read_text(encoding="utf-8")
    assert active_text.count("- [ ] [P1] t-parent-s1 — First") == 1
    assert active_text.count("- [ ] [P2] t-parent-s2 — Second") == 1


def test_commit_recovers_when_queue_has_subtasks_but_prd_is_still_draft(tmp_path: Path):
    prd_path, active, done = _setup_brain(tmp_path)
    prd_text = prd_path.read_text(encoding="utf-8")
    blocks = [item.block for item in prdfile.normalize_subtasks("t-parent", prdfile._extract_subtasks(prd_text))]
    active.write_text(
        "# Active tasks\n\n## PRD subtasks of t-parent\n\n" + "\n\n".join(blocks) + "\n",
        encoding="utf-8",
    )

    result = prdfile.commit(prd_path, active, done, "t-parent")

    assert result.recovered is True
    assert result.appended_ids == []
    assert "status: committed" in prd_path.read_text(encoding="utf-8")
    active_text = active.read_text(encoding="utf-8")
    assert active_text.count("- [ ] [P1] t-parent-s1 — First") == 1
    assert active_text.count("- [ ] [P2] t-parent-s2 — Second") == 1


def test_commit_recovers_when_prd_is_committed_but_queue_is_missing(tmp_path: Path):
    prd_path, active, done = _setup_brain(tmp_path)
    prd_path.write_text(prd_path.read_text(encoding="utf-8").replace("status: draft", "status: committed"), encoding="utf-8")

    result = prdfile.commit(prd_path, active, done, "t-parent")

    assert result.recovered is True
    assert result.appended_ids == ["t-parent-s1", "t-parent-s2"]
    active_text = active.read_text(encoding="utf-8")
    assert active_text.count("- [ ] [P1] t-parent-s1 — First") == 1
    assert active_text.count("- [ ] [P2] t-parent-s2 — Second") == 1


def test_concurrent_add_complete_and_prd_commit_preserve_all_mutations(tmp_path: Path):
    prd_path, active, done = _setup_brain(tmp_path)
    barrier = threading.Barrier(3)
    errors: list[BaseException] = []

    def run(fn) -> None:
        try:
            barrier.wait()
            fn()
        except BaseException as exc:  # pragma: no cover - surfaced via assert below
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=(lambda: prdfile.commit(prd_path, active, done, "t-parent"),)),
        threading.Thread(target=run, args=(lambda: queue.add("Concurrent add", tmp_path, acceptance="ok"),)),
        threading.Thread(target=run, args=(lambda: queue.complete("t-live", "owner-agent", "openai-gpt-5.4", tmp_path),)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    active_text = active.read_text(encoding="utf-8")
    done_text = done.read_text(encoding="utf-8")
    assert active_text.count("- [ ] [P1] t-parent-s1 — First") == 1
    assert active_text.count("- [ ] [P2] t-parent-s2 — Second") == 1
    assert "Concurrent add" in active_text
    assert "t-live" not in active_text
    assert done_text.count("t-live") == 1


def test_commit_rejects_duplicate_normalized_ids_without_writing(tmp_path: Path):
    prd_path, active, done = _setup_brain(tmp_path)
    prd_path.write_text(
        """---
id: t-parent
status: draft
---
## Subtasks

- [ ] [P1] s1 — First
      acceptance: ok

- [ ] [P1] t-parent-s1 — Duplicate
      acceptance: ok
""",
        encoding="utf-8",
    )
    active_before = active.read_bytes()
    prd_before = prd_path.read_bytes()

    try:
        prdfile.commit(prd_path, active, done, "t-parent")
    except prdfile.PRDError as exc:
        assert "duplicate normalized PRD subtask ids" in str(exc)
        assert "t-parent-s1" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected duplicate normalized ids to be rejected")

    assert active.read_bytes() == active_before
    assert prd_path.read_bytes() == prd_before


def test_commit_prepared_rejects_duplicates_without_writing(tmp_path: Path):
    prd_path, active, done = _setup_brain(tmp_path)
    prepared = [
        "- [ ] [P1] t-parent-s1 — First\n      parent: t-parent\n      acceptance: ok",
        "- [ ] [P1] t-parent-s1 — Duplicate\n      parent: t-parent\n      acceptance: ok",
    ]
    active_before = active.read_bytes()
    prd_before = prd_path.read_bytes()

    try:
        prdfile.commit_prepared(prd_path, active, done, "t-parent", prepared)
    except prdfile.PRDError as exc:
        assert "duplicate normalized PRD subtask ids" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected duplicate prepared ids to be rejected")

    assert active.read_bytes() == active_before
    assert prd_path.read_bytes() == prd_before
