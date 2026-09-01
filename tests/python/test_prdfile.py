from __future__ import annotations

import re
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


def test_commit_rejects_unparsable_subtask_without_writing(tmp_path: Path):
    """t-2026-08-14-prd-malformed-subtask-rejectio.

    A block that find_blocks() matches (non-empty header line) but
    parse_block() cannot read (missing the required em-dash separator)
    used to be silently dropped by normalize_subtasks(): the rest of the
    PRD committed fine and the malformed subtask vanished from the PRD,
    active.md and the log without a trace. It must instead reject the
    whole batch atomically, the same way `brain-prd dry-run` already does
    for identical input.
    """
    prd_path, active, done = _setup_brain(tmp_path)
    prd_path.write_text(
        """---
id: t-parent
status: draft
---
## Subtasks

- [ ] [P1] s1 -- First
      role: developer
      acceptance: ok

- [ ] [P2] s2 — Second
      role: developer
      acceptance: ok
""",
        encoding="utf-8",
    )
    active_before = active.read_bytes()
    prd_before = prd_path.read_bytes()

    try:
        prdfile.commit(prd_path, active, done, "t-parent")
    except prdfile.PRDError as exc:
        assert "invalid subtask header" in str(exc)
        assert "s1" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected unparsable subtask block to be rejected")

    assert active.read_bytes() == active_before
    assert prd_path.read_bytes() == prd_before


def test_commit_prepared_rejects_unparsable_block_without_writing(tmp_path: Path):
    prd_path, active, done = _setup_brain(tmp_path)
    prepared = [
        "- [ ] [P1] t-parent-s1 -- First\n      parent: t-parent\n      acceptance: ok",
        "- [ ] [P1] t-parent-s2 — Second\n      parent: t-parent\n      acceptance: ok",
    ]
    active_before = active.read_bytes()
    prd_before = prd_path.read_bytes()

    try:
        prdfile.commit_prepared(prd_path, active, done, "t-parent", prepared)
    except prdfile.PRDError as exc:
        assert "invalid subtask header" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected unparsable prepared block to be rejected")

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


# ---------------------------------------------------------------------------
# t-2026-08-14-prd-decompose-log-transaction: the audit record is written
# inside the queue transaction, not appended afterwards.
# ---------------------------------------------------------------------------


def _log_path(tmp_path: Path) -> Path:
    return tmp_path / "wiki" / "log.md"


def _count_audit_lines(log_path: Path, op: str, parent_id: str) -> int:
    if not log_path.exists():
        return 0
    pat = re.compile(rf"(?m)^## \[[^\]]*\] {re.escape(op)} \| {re.escape(parent_id)} \|")
    return len(pat.findall(log_path.read_text(encoding="utf-8")))


def test_commit_writes_audit_line_and_reports_it(tmp_path: Path):
    prd_path, active, done = _setup_brain(tmp_path)
    log = _log_path(tmp_path)

    result = prdfile.commit(prd_path, active, done, "t-parent", log_path=log)

    assert result.audited is True
    assert _count_audit_lines(log, "prd-commit", "t-parent") == 1
    line = log.read_text(encoding="utf-8")
    assert "subtasks=2 appended=2 recovered=0" in line
    assert "sig=" in line


def test_commit_audit_line_is_idempotent_on_recommit(tmp_path: Path):
    prd_path, active, done = _setup_brain(tmp_path)
    log = _log_path(tmp_path)

    first = prdfile.commit(prd_path, active, done, "t-parent", log_path=log)
    second = prdfile.commit(prd_path, active, done, "t-parent", log_path=log)

    assert first.audited is True
    assert second.audited is False
    assert _count_audit_lines(log, "prd-commit", "t-parent") == 1


def test_commit_audit_line_is_recovered_when_queue_committed_but_log_missing(tmp_path: Path):
    """Crash between the queue write and the old, separate log append: the retry
    sees the queue already committed and still writes the missing audit line."""
    prd_path, active, done = _setup_brain(tmp_path)
    log = _log_path(tmp_path)

    crashed = prdfile.commit(prd_path, active, done, "t-parent")  # no log_path — never logged
    assert crashed.audited is False
    assert _count_audit_lines(log, "prd-commit", "t-parent") == 0

    recovered = prdfile.commit(prd_path, active, done, "t-parent", log_path=log)
    assert recovered.appended_ids == []          # queue already has them
    assert recovered.audited is True             # audit line now written
    assert _count_audit_lines(log, "prd-commit", "t-parent") == 1


def test_commit_rejection_writes_no_audit_line(tmp_path: Path):
    prd_path, active, done = _setup_brain(tmp_path)
    log = _log_path(tmp_path)
    prd_path.write_text(
        "---\nid: t-parent\nstatus: draft\n---\n## Subtasks\n\n"
        "- [ ] [P1] s1 — First\n      acceptance: ok\n\n"
        "- [ ] [P1] t-parent-s1 — Duplicate\n      acceptance: ok\n",
        encoding="utf-8",
    )
    try:
        prdfile.commit(prd_path, active, done, "t-parent", log_path=log)
    except prdfile.PRDError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected rejection")
    assert _count_audit_lines(log, "prd-commit", "t-parent") == 0


def test_concurrent_commits_of_one_prd_write_exactly_one_audit_line(tmp_path: Path):
    prd_path, active, done = _setup_brain(tmp_path)
    log = _log_path(tmp_path)
    barrier = threading.Barrier(4)
    errors: list[BaseException] = []
    audited_flags: list[bool] = []

    def run() -> None:
        try:
            barrier.wait()
            res = prdfile.commit(prd_path, active, done, "t-parent", log_path=log)
            audited_flags.append(res.audited)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert sum(audited_flags) == 1               # exactly one writer logged
    assert _count_audit_lines(log, "prd-commit", "t-parent") == 1
    assert active.read_text(encoding="utf-8").count("- [ ] [P1] t-parent-s1 — First") == 1


def test_concurrent_commits_of_two_prds_keep_both_audit_lines(tmp_path: Path):
    prd_a, active, done = _setup_brain(tmp_path)
    prd_b = prd_a.parent / "t-other.md"
    prd_b.write_text(PRD.replace("t-parent", "t-other"), encoding="utf-8")
    log = _log_path(tmp_path)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def run(prd: Path, parent: str) -> None:
        try:
            barrier.wait()
            prdfile.commit(prd, active, done, parent, log_path=log)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=(prd_a, "t-parent")),
        threading.Thread(target=run, args=(prd_b, "t-other")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert _count_audit_lines(log, "prd-commit", "t-parent") == 1
    assert _count_audit_lines(log, "prd-commit", "t-other") == 1
    for ln in log.read_text(encoding="utf-8").splitlines():
        if "prd-commit |" in ln:
            assert ln.startswith("## [") and ln.count(" | ") >= 3


def test_commit_prepared_audit_line_uses_decompose_op(tmp_path: Path):
    prd_path, active, done = _setup_brain(tmp_path)
    log = _log_path(tmp_path)
    blocks = [
        "- [ ] [P1] t-parent-s1 — First\n      parent: t-parent\n      role: developer\n      acceptance: ok",
        "- [ ] [P2] t-parent-s2 — Second\n      parent: t-parent\n      role: developer\n      acceptance: ok",
    ]
    result = prdfile.commit_prepared(
        prd_path, active, done, "t-parent", blocks,
        log_path=log, audit_agent="agent-x", audit_extra_tail=" stub=False",
    )
    assert result.audited is True
    line = next(
        ln for ln in log.read_text(encoding="utf-8").splitlines()
        if "prd-decompose | t-parent |" in ln
    )
    assert "agent-x" in line
    assert "stub=False" in line
    assert "sig=" in line
    assert _count_audit_lines(log, "prd-commit", "t-parent") == 0
