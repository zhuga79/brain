from contextlib import contextmanager, nullcontext
from pathlib import Path
import os
import subprocess
import sys
import threading

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SRC_LIB = REPO / "runtime" / "lib"
sys.path.insert(0, str(SRC_LIB))
if "brain_workspace" in sys.modules:
    loaded_from = Path(getattr(sys.modules["brain_workspace"], "__file__", "")).resolve()
    if not loaded_from.is_relative_to(SRC_LIB):
        del sys.modules["brain_workspace"]

from brain_workspace import (
    append_local_log,
    complete_local_task,
    discover_workspaces,
    find_nearest_workspace,
    is_role_allowed,
    next_local_task,
    parse_local_log,
    parse_local_log_entries,
    parse_local_tasks,
    parse_workspace_policy,
    take_local_task,
    update_local_task_state,
)


def test_brain_workspace_imports_with_system_python():
    python = Path("/usr/bin/python3")
    if not python.exists():
        return
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_LIB)

    result = subprocess.run(
        [str(python), "-c", "import brain_workspace"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_discover_workspaces_ignores_vendor_and_cache_dirs(tmp_path):
    root = tmp_path / "root"
    (root / "project-a").mkdir(parents=True)
    (root / "project-a" / "BRAIN.md").write_text("# Workspace: A\n", encoding="utf-8")
    (root / "project-a" / "TASKS.md").write_text("# Local Tasks\n", encoding="utf-8")
    (root / "project-a" / "LOG.md").write_text("# Local Log\n", encoding="utf-8")
    (root / "project-b" / ".git" / "ignored").mkdir(parents=True)
    (root / "project-b" / ".git" / "ignored" / "BRAIN.md").write_text("# Ignored\n", encoding="utf-8")
    (root / "project-b" / ".venv" / "ignored").mkdir(parents=True)
    (root / "project-b" / ".venv" / "ignored" / "BRAIN.md").write_text("# Ignored\n", encoding="utf-8")
    (root / "project-b").mkdir(exist_ok=True)
    (root / "project-b" / "BRAIN.md").write_text("# Workspace: B\n", encoding="utf-8")

    found = discover_workspaces([root])

    assert [item.path.name for item in found] == ["project-a", "project-b"]
    assert found[0].title == "A"  # "Workspace:" prefix stripped (informative)
    assert found[0].has_tasks is True
    assert found[0].has_log is True


def test_find_nearest_workspace_walks_up(tmp_path):
    workspace = tmp_path / "root" / "project" / "sub"
    workspace.mkdir(parents=True)
    (tmp_path / "root" / "project" / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")

    assert find_nearest_workspace(workspace) == tmp_path / "root" / "project"


def test_parse_local_tasks_extracts_open_items_and_metadata(tmp_path):
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] local-001 - Draft local rules
      role: pm
      acceptance: BRAIN.md states write rules.

- [x] [P2] local-002 - Done item
      role: developer
      acceptance: Already complete.
""",
        encoding="utf-8",
    )

    parsed = parse_local_tasks(tasks)

    assert len(parsed) == 2
    assert parsed[0].state == "open"
    assert parsed[0].priority == "P1"
    assert parsed[0].task_id == "local-001"
    assert parsed[0].title == "Draft local rules"
    assert parsed[0].role == "pm"
    assert parsed[0].acceptance == "BRAIN.md states write rules."
    assert parsed[1].state == "done"


def test_parse_local_tasks_accepts_canonical_brain_headers(tmp_path):
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] local-001 — Draft local rules
      role: pm
      acceptance: BRAIN.md states write rules.

- [x] [P2] local-002 — Done item
      role: developer
      acceptance: Already complete.
""",
        encoding="utf-8",
    )

    parsed = parse_local_tasks(tasks)

    assert [task.task_id for task in parsed] == ["local-001", "local-002"]
    assert parsed[0].title == "Draft local rules"
    assert parsed[1].state == "done"


def test_parse_local_log_returns_latest_entry(tmp_path):
    log = tmp_path / "LOG.md"
    log.write_text(
        """# Local Log

## 2026-05-26T10:00:00Z | agent-a | older

- Older action.

## 2026-05-27T18:31:29Z | agent-b | latest

- Latest action.
""",
        encoding="utf-8",
    )

    latest = parse_local_log(log)

    assert latest is not None
    assert latest.timestamp == "2026-05-27T18:31:29Z"
    assert latest.agent == "agent-b"
    assert latest.summary == "latest"


def test_next_local_task_filters_by_role_and_skips_busy_items(tmp_path):
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [~] [P0] local-busy - Busy item
      role: developer
      acceptance: Already taken.

- [ ] [P1] local-pm - PM item
      role: pm
      acceptance: PM can take it.

- [ ] [P2] local-dev - Developer item
      role: developer
      acceptance: Developer can take it.
""",
        encoding="utf-8",
    )

    assert next_local_task(tasks, role="developer").task_id == "local-dev"
    assert next_local_task(tasks, role="pm").task_id == "local-pm"
    assert next_local_task(tasks, role="lawyer") is None


def test_next_local_task_uses_canonical_tasks_headers(tmp_path):
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [~] [P0] local-busy — Busy item
      role: developer
      acceptance: Already taken.

- [ ] [P1] local-dev — Developer item
      role: developer
      acceptance: Developer can take it.
""",
        encoding="utf-8",
    )

    assert next_local_task(tasks, role="developer").task_id == "local-dev"


def test_parse_workspace_policy_reads_role_groups_and_action_gates(tmp_path):
    brain = tmp_path / "BRAIN.md"
    brain.write_text(
        """# Workspace: Legal

## Workspace Profile

type: legal-commercial-contract
primary_role: pm

## Role Policy

core:
- pm

available:
- lawyer
- paralegal

gated:
- tax-advisor

blocked:
- developer

## Action Gates

requires_user_approval:
- отправка писем
- изменение подписанных документов
""",
        encoding="utf-8",
    )

    policy = parse_workspace_policy(brain)

    assert policy.workspace_type == "legal-commercial-contract"
    assert policy.primary_role == "pm"
    assert policy.core == ("pm",)
    assert policy.available == ("lawyer", "paralegal")
    assert policy.gated == ("tax-advisor",)
    assert policy.blocked == ("developer",)
    assert policy.requires_user_approval == ("отправка писем", "изменение подписанных документов")
    assert is_role_allowed(policy, "lawyer") is True
    assert is_role_allowed(policy, "tax-advisor") is True
    assert is_role_allowed(policy, "developer") is False
    assert is_role_allowed(policy, "designer") is False


def test_next_local_task_rejects_roles_blocked_by_workspace_policy(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text(
        """# Workspace

## Role Policy

core:
- pm

available:
- lawyer

blocked:
- developer
""",
        encoding="utf-8",
    )
    (workspace / "TASKS.md").write_text(
        """# Local Tasks

- [ ] [P1] local-dev - Developer item
      role: developer
      acceptance: Developer should be blocked.

- [ ] [P1] local-law - Legal item
      role: lawyer
      acceptance: Lawyer may take it.
""",
        encoding="utf-8",
    )

    assert next_local_task(workspace / "TASKS.md", role="developer", brain_path=workspace / "BRAIN.md") is None
    assert next_local_task(workspace / "TASKS.md", role="lawyer", brain_path=workspace / "BRAIN.md").task_id == "local-law"


def test_update_local_task_state_preserves_metadata(tmp_path):
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] local-001 - Draft local rules
      role: pm
      acceptance: BRAIN.md states write rules.
""",
        encoding="utf-8",
    )

    changed = update_local_task_state(tasks, "local-001", "in-progress")

    assert changed.task_id == "local-001"
    assert changed.state == "in-progress"
    content = tasks.read_text(encoding="utf-8")
    assert "- [~] [P1] local-001 - Draft local rules" in content
    assert "acceptance: BRAIN.md states write rules." in content


def test_update_local_task_state_rejects_unexpected_current_state(tmp_path):
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [x] [P1] local-001 - Closed task
      role: pm
      acceptance: Already closed.
""",
        encoding="utf-8",
    )

    try:
        update_local_task_state(tasks, "local-001", "in-progress", from_states=("open",))
    except ValueError as exc:
        assert "expected state open" in str(exc)
    else:
        raise AssertionError("state transition unexpectedly succeeded")


def test_append_local_log_creates_workspace_log_entry(tmp_path):
    log = tmp_path / "LOG.md"

    append_local_log(
        log,
        timestamp="2026-05-28T12:00:00Z",
        agent="agent-a",
        summary="took local-001",
        detail="Moved local-001 to in-progress.",
    )

    content = log.read_text(encoding="utf-8")
    assert content.startswith("# Local Log\n")
    assert "## 2026-05-28T12:00:00Z | agent-a | took local-001" in content
    assert "- Moved local-001 to in-progress." in content


def test_take_local_task_records_owner_started_and_rejects_non_open(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    (workspace / "TASKS.md").write_text(
        """# Local Tasks

- [ ] [P1] local-001 - Draft local rules
      role: developer
      acceptance: Rules drafted.
""",
        encoding="utf-8",
    )

    task = take_local_task(workspace, "local-001", "agent-a")

    assert task.task_id == "local-001"
    assert task.state == "in-progress"
    content = (workspace / "TASKS.md").read_text(encoding="utf-8")
    assert "- [~] [P1] local-001 - Draft local rules" in content
    assert "started:" in content
    assert "by: agent-a" in content

    try:
        take_local_task(workspace, "local-001", "agent-b")
    except ValueError as exc:
        assert "expected state open" in str(exc)
    else:
        raise AssertionError("second take unexpectedly succeeded")


def test_complete_local_task_requires_owner_in_progress_and_model(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    (workspace / "TASKS.md").write_text(
        """# Local Tasks

- [~] [P1] local-001 - Draft local rules
      role: developer
      acceptance: Rules drafted.
      started: 2026-08-14T10:00:00Z
      by: agent-a
""",
        encoding="utf-8",
    )
    (workspace / "LOG.md").write_text("# Local Log\n", encoding="utf-8")

    try:
        complete_local_task(workspace, "local-001", "agent-b", "openai-gpt-5.4", "done")
    except ValueError as exc:
        assert "owned by agent-a" in str(exc)
    else:
        raise AssertionError("foreign complete unexpectedly succeeded")

    try:
        complete_local_task(workspace, "local-001", "agent-a", "", "done")
    except ValueError as exc:
        assert "model signature required" in str(exc)
    else:
        raise AssertionError("unsigned complete unexpectedly succeeded")

    task = complete_local_task(workspace, "local-001", "agent-a", "openai-gpt-5.4", "done")

    assert task.state == "done"
    content = (workspace / "TASKS.md").read_text(encoding="utf-8")
    assert "- [x] [P1] local-001 - Draft local rules" in content
    assert "by: agent-a" in content
    assert "model: openai-gpt-5.4" in content
    assert "completed:" in content
    log = (workspace / "LOG.md").read_text(encoding="utf-8")
    assert "## " in log
    assert "agent-a | done" in log


def test_complete_local_task_rejects_open_task_transition(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    (workspace / "TASKS.md").write_text(
        """# Local Tasks

- [ ] [P1] local-001 - Draft local rules
      role: developer
      acceptance: Rules drafted.
""",
        encoding="utf-8",
    )

    try:
        complete_local_task(workspace, "local-001", "agent-a", "openai-gpt-5.4", "done")
    except ValueError as exc:
        assert "expected state in-progress" in str(exc)
    else:
        raise AssertionError("open task completed directly")


def test_complete_local_task_recovers_after_log_write_crash(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    (workspace / "TASKS.md").write_text(
        """# Local Tasks

- [~] [P1] local-001 - Draft local rules
      role: developer
      acceptance: Rules drafted.
      started: 2026-08-14T10:00:00Z
      by: agent-a
""",
        encoding="utf-8",
    )
    (workspace / "LOG.md").write_text("# Local Log\n", encoding="utf-8")

    import brain_workspace as workspace_mod

    real_atomic_write = workspace_mod.atomic.write_text
    seen_log_write = {"raised": False}

    def crash_once(path, text, *, prefix=".tmp."):
        real_atomic_write(path, text, prefix=prefix)
        if path.name == "TASKS.md" and not seen_log_write["raised"]:
            seen_log_write["raised"] = True
            raise RuntimeError("simulated crash after task write")

    monkeypatch.setattr(workspace_mod.atomic, "write_text", crash_once)

    try:
        complete_local_task(workspace, "local-001", "agent-a", "openai-gpt-5.4", "done")
    except RuntimeError as exc:
        assert "simulated crash" in str(exc)
    else:
        raise AssertionError("simulated crash did not fire")

    monkeypatch.setattr(workspace_mod.atomic, "write_text", real_atomic_write)

    task = complete_local_task(workspace, "local-001", "agent-a", "openai-gpt-5.4", "done")

    assert task.state == "done"
    assert not (workspace / ".workspace-queue-journal.json").exists()
    entries = parse_local_log_entries(workspace / "LOG.md", limit=8)
    matching = [entry for entry in entries if entry.summary == "done"]
    assert len(matching) == 1


def test_take_local_task_serializes_parallel_writers(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    (workspace / "LOG.md").write_text("# Local Log\n", encoding="utf-8")
    (workspace / "TASKS.md").write_text(
        "# Local Tasks\n\n"
        + "\n\n".join(
            f"- [ ] [P1] local-{i:02d} - Draft local rules {i:02d}\n"
            "      role: developer\n"
            "      acceptance: Rules drafted."
            for i in range(1, 7)
        )
        + "\n",
        encoding="utf-8",
    )

    failures: list[str] = []

    def worker(i: int) -> None:
        try:
            take_local_task(workspace, f"local-{i:02d}", f"agent-{i:02d}")
        except Exception as exc:  # pragma: no cover - diagnostics
            failures.append(str(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, 7)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    tasks = {task.task_id: task for task in parse_local_tasks(workspace / "TASKS.md")}
    assert all(tasks[f"local-{i:02d}"].state == "in-progress" for i in range(1, 7))
    log_entries = parse_local_log_entries(workspace / "LOG.md", limit=16)
    took_entries = [entry for entry in log_entries if entry.summary.startswith("took local-")]
    assert len(took_entries) == 6


def test_recover_workspace_transaction_accepts_mixed_crash_state(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tasks_path = workspace / "TASKS.md"
    log_path = workspace / "LOG.md"
    tasks_before = """# Local Tasks

- [ ] [P1] local-001 - Draft local rules
      role: developer
      acceptance: Rules drafted.
"""
    tasks_after = """# Local Tasks

- [~] [P1] local-001 - Draft local rules
      role: developer
      acceptance: Rules drafted.
      started: 2026-08-14T10:00:00Z
      by: agent-a
"""
    log_before = "# Local Log\n"
    log_after = """# Local Log

## 2026-08-14T10:00:00Z | agent-a | took local-001

- Moved local-001 to in-progress.
"""
    tasks_path.write_text(tasks_after, encoding="utf-8")
    log_path.write_text(log_before, encoding="utf-8")

    _W._write_workspace_journal(
        workspace,
        operation="take",
        task_id="local-001",
        tasks_before=tasks_before,
        log_before=log_before,
        tasks_after=tasks_after,
        log_after=log_after,
    )

    _W._recover_workspace_transaction(workspace)

    assert tasks_path.read_text(encoding="utf-8") == tasks_after
    assert log_path.read_text(encoding="utf-8") == log_after
    assert not (workspace / ".workspace-queue-journal.json").exists()


def test_recover_workspace_transaction_accepts_newer_log_if_tasks_match_after(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tasks_path = workspace / "TASKS.md"
    log_path = workspace / "LOG.md"
    tasks_before = """# Local Tasks

- [~] [P1] local-001 - Draft local rules
      role: developer
      acceptance: Rules drafted.
      started: 2026-08-14T10:00:00Z
      by: agent-a
"""
    tasks_after = """# Local Tasks

- [x] [P1] local-001 - Draft local rules
      role: developer
      acceptance: Rules drafted.
      started: 2026-08-14T10:00:00Z
      by: agent-a
      model: openai-gpt-5.4
      completed: 2026-08-14T10:05:00Z
"""
    log_before = "# Local Log\n"
    log_after = """# Local Log

## 2026-08-14T10:05:00Z | agent-a | completed local-001

- Moved local-001 to done.
"""
    newer_log = log_after + "\n## 2026-08-14T10:06:00Z | agent-b | later\n\n- Follow-up.\n"
    tasks_path.write_text(tasks_after, encoding="utf-8")
    log_path.write_text(newer_log, encoding="utf-8")

    _W._write_workspace_journal(
        workspace,
        operation="complete",
        task_id="local-001",
        tasks_before=tasks_before,
        log_before=log_before,
        tasks_after=tasks_after,
        log_after=log_after,
    )

    try:
        _W._recover_workspace_transaction(workspace)
    except ValueError as exc:
        assert "conflict" in str(exc).lower()
    else:
        raise AssertionError("stale newer log unexpectedly overwritten")

    assert tasks_path.read_text(encoding="utf-8") == tasks_after
    assert log_path.read_text(encoding="utf-8") == newer_log
    assert (workspace / ".workspace-queue-journal.json").exists()


def test_recover_workspace_transaction_accepts_newer_tasks_if_log_matches_after(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tasks_path = workspace / "TASKS.md"
    log_path = workspace / "LOG.md"
    tasks_before = """# Local Tasks

- [ ] [P1] local-001 - Draft local rules
      role: developer
      acceptance: Rules drafted.
"""
    tasks_after = """# Local Tasks

- [~] [P1] local-001 - Draft local rules
      role: developer
      acceptance: Rules drafted.
      started: 2026-08-14T10:00:00Z
      by: agent-a
"""
    newer_tasks = tasks_after + """
- [ ] [P2] local-002 - Later task
      role: developer
      acceptance: Later.
"""
    log_before = "# Local Log\n"
    log_after = """# Local Log

## 2026-08-14T10:00:00Z | agent-a | took local-001

- Moved local-001 to in-progress.
"""
    tasks_path.write_text(newer_tasks, encoding="utf-8")
    log_path.write_text(log_after, encoding="utf-8")

    _W._write_workspace_journal(
        workspace,
        operation="take",
        task_id="local-001",
        tasks_before=tasks_before,
        log_before=log_before,
        tasks_after=tasks_after,
        log_after=log_after,
    )

    try:
        _W._recover_workspace_transaction(workspace)
    except ValueError as exc:
        assert "conflict" in str(exc).lower()
    else:
        raise AssertionError("stale newer tasks unexpectedly overwritten")

    assert tasks_path.read_text(encoding="utf-8") == newer_tasks
    assert log_path.read_text(encoding="utf-8") == log_after
    assert (workspace / ".workspace-queue-journal.json").exists()


def test_recover_workspace_transaction_preserves_files_on_conflict(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tasks_path = workspace / "TASKS.md"
    log_path = workspace / "LOG.md"
    journal_path = workspace / ".workspace-queue-journal.json"
    tasks_before = "# Local Tasks\n"
    tasks_after = "# Local Tasks\n\n- [ ] [P1] local-001 - Draft local rules\n"
    log_before = "# Local Log\n"
    log_after = "# Local Log\n\n## 2026-08-14T10:00:00Z | agent-a | took local-001\n"
    tasks_conflict = "# Local Tasks\n\n- [!] [P1] local-001 - Diverged\n"
    log_conflict = "# Local Log\n\n## 2026-08-14T11:00:00Z | agent-b | diverged\n"
    tasks_path.write_text(tasks_conflict, encoding="utf-8")
    log_path.write_text(log_conflict, encoding="utf-8")

    _W._write_workspace_journal(
        workspace,
        operation="take",
        task_id="local-001",
        tasks_before=tasks_before,
        log_before=log_before,
        tasks_after=tasks_after,
        log_after=log_after,
    )
    journal_before = journal_path.read_bytes()

    try:
        _W._recover_workspace_transaction(workspace)
    except ValueError as exc:
        assert "conflict" in str(exc).lower()
    else:
        raise AssertionError("conflict unexpectedly recovered")

    assert tasks_path.read_text(encoding="utf-8") == tasks_conflict
    assert log_path.read_text(encoding="utf-8") == log_conflict
    assert journal_path.read_bytes() == journal_before


def test_recover_workspace_transaction_rejects_forged_journal_without_mutation(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tasks_path = workspace / "TASKS.md"
    log_path = workspace / "LOG.md"
    journal_path = workspace / ".workspace-queue-journal.json"
    tasks_text = "# Local Tasks\n"
    log_text = "# Local Log\n"
    tasks_path.write_text(tasks_text, encoding="utf-8")
    log_path.write_text(log_text, encoding="utf-8")
    journal_path.write_text(
        """{
  "version": "1",
  "operation": "take",
  "task_id": "local-001",
  "tasks_before_hash": "abc",
  "log_before_hash": "def",
  "tasks_after_hash": "mismatch",
  "log_after_hash": "mismatch",
  "tasks_after": "# Local Tasks\\nforged\\n",
  "log_after": "# Local Log\\nforged\\n"
}
""",
        encoding="utf-8",
    )
    journal_before = journal_path.read_bytes()

    try:
        _W._recover_workspace_transaction(workspace)
    except ValueError as exc:
        assert "invalid workspace journal" in str(exc).lower()
    else:
        raise AssertionError("forged journal unexpectedly accepted")

    assert tasks_path.read_text(encoding="utf-8") == tasks_text
    assert log_path.read_text(encoding="utf-8") == log_text
    assert journal_path.read_bytes() == journal_before


def test_convert_folder_to_workspace(tmp_path):
    from brain_workspace import convert_folder_to_workspace, parse_local_tasks
    
    workspace_dir = tmp_path / "new_workspace"
    workspace_dir.mkdir()
    
    descriptor = {
        "name": "My Test Workspace",
        "goal": "This is a test workspace for task decomposition.",
        "tasks": [
            "Simple task 1",
            {"title": "Task with explicit role", "role": "developer", "acceptance": "Code implemented and tested."},
            "Implement feature X",  # Should default to developer
            "Fix bug in UI component", # Should infer developer and designer
            "Write documentation for API", # Should infer copywriter
            "Refactor old code", # Should infer reviewer
            {"title": "Another dev task", "role": "developer"},
            "", # Empty task to be skipped
            "Simple task 1", # Duplicate of string task
        ],
    }

    # First run: convert the folder
    workspace_info = convert_folder_to_workspace(workspace_dir, descriptor)

    assert workspace_info.path == workspace_dir
    assert workspace_info.title == "My Test Workspace"
    
    brain_file = workspace_dir / "BRAIN.md"
    tasks_file = workspace_dir / "TASKS.md"

    assert brain_file.exists()
    assert tasks_file.exists()

    brain_content = brain_file.read_text(encoding="utf-8")
    assert "# My Test Workspace" in brain_content
    assert "This is a test workspace for task decomposition." in brain_content

    tasks_content = tasks_file.read_text(encoding="utf-8")
    assert "# Tasks" in tasks_content
    
    parsed_tasks = parse_local_tasks(tasks_file)
    assert len(parsed_tasks) == 7 # Simple task 1, Task with explicit role, Implement feature X, Fix bug in UI component, Write documentation for API, Refactor old code, Another dev task

    # Verify task details
    task1 = parsed_tasks[0]
    assert task1.title == "Simple task 1"
    assert task1.role == "developer" # Default role
    assert task1.acceptance == ""

    task_with_explicit_role = parsed_tasks[1]
    assert task_with_explicit_role.title == "Task with explicit role"
    assert task_with_explicit_role.role == "developer"
    assert task_with_explicit_role.acceptance == "Code implemented and tested."

    implement_feature_x = parsed_tasks[2]
    assert implement_feature_x.title == "Implement feature X"
    assert implement_feature_x.role == "developer" # Default role
    assert implement_feature_x.acceptance == ""

    fix_bug_ui = parsed_tasks[3]
    assert fix_bug_ui.title == "Fix bug in UI component"
    assert fix_bug_ui.role == "developer" # "fix" keyword (a bug-fix) takes precedence over "UI"
    assert fix_bug_ui.acceptance == ""

    write_doc = parsed_tasks[4]
    assert write_doc.title == "Write documentation for API"
    assert write_doc.role == "copywriter" # Inferred from "documentation" (doc) keyword
    assert write_doc.acceptance == ""

    refactor_code = parsed_tasks[5]
    assert refactor_code.title == "Refactor old code"
    assert refactor_code.role == "reviewer" # Inferred from "refactor" keyword
    assert refactor_code.acceptance == ""
    
    another_dev_task = parsed_tasks[6]
    assert another_dev_task.title == "Another dev task"
    assert another_dev_task.role == "developer"
    assert another_dev_task.acceptance == ""

    # Test idempotency and adding new tasks
    new_descriptor = {
        "name": "My Test Workspace",
        "goal": "This is a test workspace for task decomposition.",
        "tasks": [
            {"title": "Task with explicit role", "role": "developer", "acceptance": "Code implemented and tested."}, # Existing task
            "New task for update",
            {"title": "Final task", "role": "architect", "acceptance": "Design document approved."},
            "Simple task 1", # Existing string task
            "", # Empty task
        ],
    }
    
    convert_folder_to_workspace(workspace_dir, new_descriptor)
    
    updated_parsed_tasks = parse_local_tasks(tasks_file)
    # Original 7 tasks + 2 new tasks = 9
    assert len(updated_parsed_tasks) == 9

    # Verify new tasks are added and existing ones are not duplicated
    new_task = updated_parsed_tasks[7]
    assert new_task.title == "New task for update"
    assert new_task.role == "developer" # Default role
    
    final_task = updated_parsed_tasks[8]
    assert final_task.title == "Final task"
    assert final_task.role == "architect"
    assert final_task.acceptance == "Design document approved."

    # Ensure no duplicates of existing tasks by checking task_ids
    task_ids = {task.task_id for task in updated_parsed_tasks}
    assert len(task_ids) == 9


def test_convert_folder_to_workspace_generates_ascii_ids_for_cyrillic_titles(tmp_path):
    from brain_workspace import convert_folder_to_workspace, parse_local_tasks

    workspace_dir = tmp_path / "cyrillic_workspace"
    workspace_dir.mkdir()

    descriptor = {
        "name": "Кириллический проект",
        "goal": "Проверить импорт задач.",
        "tasks": [
            "Подготовить договор",
            {"title": "Проверить UI форму", "role": "developer"},
        ],
    }

    convert_folder_to_workspace(workspace_dir, descriptor)
    parsed_tasks = parse_local_tasks(workspace_dir / "TASKS.md")

    assert len(parsed_tasks) == 2
    for task in parsed_tasks:
        assert task.task_id.isascii()
        assert task.task_id.startswith("t-")
        assert all(ch.isalnum() or ch == "-" for ch in task.task_id)


# --- t-2026-06-29-dashboard-autodiscover ---
import brain_workspace as _W
from pathlib import Path as _P


def test_discover_prunes_and_depth(tmp_path):
    (tmp_path / "proj-a").mkdir()
    (tmp_path / "proj-a" / "BRAIN.md").write_text("# Acme API\n")
    (tmp_path / "junk" / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "junk" / "node_modules" / "pkg" / "BRAIN.md").write_text("# pruned\n")
    deep = tmp_path.joinpath(*[f"d{i}" for i in range(8)])
    deep.mkdir(parents=True)
    (deep / "BRAIN.md").write_text("# too deep\n")
    ws = _W.discover_workspaces([tmp_path], max_depth=6)
    titles = {w.title for w in ws}
    assert "Acme API" in titles
    assert "pruned" not in titles      # node_modules pruned
    assert "too deep" not in titles    # depth-capped


def test_discover_excludes_host(tmp_path):
    (tmp_path / "BRAIN.md").write_text("# Host\n")
    assert _W.discover_workspaces([tmp_path], exclude=[tmp_path]) == []


def test_discover_tolerates_one_malformed_tasks_file(tmp_path):
    """A single TASKS.md that fails fail-closed parsing must not abort the scan
    or hide its own workspace — discovery is a read path."""
    good = tmp_path / "good"
    good.mkdir()
    (good / "BRAIN.md").write_text("# Good WS\n")
    (good / "TASKS.md").write_text("- [ ] [P1] g-1 - Fine\n      role: developer\n      acceptance: ok.\n")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "BRAIN.md").write_text("# Bad WS\n")
    (bad / "TASKS.md").write_text(
        "- [ ] [P1] b-1 - Broken\n      role: developer\n      depends_on: [missing-dep]\n      acceptance: no.\n"
    )
    titles = {w.title for w in _W.discover_workspaces([tmp_path])}
    assert titles == {"Good WS", "Bad WS"}
    bad_info = next(w for w in _W.discover_workspaces([tmp_path]) if w.title == "Bad WS")
    assert bad_info.open_tasks == 0  # unparsable file degrades to no tasks


def test_read_title_informative(tmp_path):
    f = tmp_path / "BRAIN.md"
    f.write_text("# Acme Billing API\n")
    assert _W._read_title(f) == "Acme Billing API"


def test_read_title_strips_prefix_and_placeholder(tmp_path):
    d = tmp_path / "data-pipeline"; d.mkdir()
    f = d / "BRAIN.md"
    f.write_text("# Workspace: <name>\n")        # placeholder -> folder name
    assert _W._read_title(f) == "data-pipeline"
    f.write_text("# Workspace: Acme\n")           # prefix stripped
    assert _W._read_title(f) == "Acme"


def test_scaffold_brain_md_is_informative(tmp_path):
    info = _W.convert_folder_to_workspace(tmp_path / "proj", {"name": "Acme", "goal": "Биллинг"})
    text = (tmp_path / "proj" / "BRAIN.md").read_text()
    assert text.startswith("# Acme")
    assert "Биллинг" in text and "created:" in text and "status:" in text


def test_discover_excludes_host_subtree(tmp_path):
    host = tmp_path / "brain"
    (host / "runtime" / "templates" / "workspace").mkdir(parents=True)
    (host / "runtime" / "templates" / "workspace" / "BRAIN.md").write_text("# <Project Name>\n")
    (tmp_path / "real-proj").mkdir()
    (tmp_path / "real-proj" / "BRAIN.md").write_text("# Real Project\n")
    ws = _W.discover_workspaces([tmp_path], exclude=[host])
    titles = {w.title for w in ws}
    assert "Real Project" in titles
    assert all("templates" not in str(w.path) for w in ws)  # host subtree excluded


def test_parse_local_tasks_stops_field_value_at_next_field(tmp_path):
    """Несколько полей в одной строке — обычная запись центральной очереди.

    split(":", 1) отдавал роль вместе с хвостом (`lawyer   mode: solo`), после
    чего фильтр по роли и политика workspace не находили задачу никогда.
    """
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] local-001 — Проверить договор
      role: lawyer   mode: solo   client: ООО Ромашка
      acceptance: договор проверен
""",
        encoding="utf-8",
    )

    parsed = parse_local_tasks(tasks)

    assert len(parsed) == 1
    assert parsed[0].role == "lawyer"
    assert parsed[0].acceptance == "договор проверен"


def test_next_local_task_finds_item_whose_line_carries_several_fields(tmp_path):
    brain = tmp_path / "BRAIN.md"
    brain.write_text(
        """# Дело

## Role Policy

core:
- lawyer

available:
- developer

blocked:
- none
""",
        encoding="utf-8",
    )
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] local-001 — Проверить договор
      role: lawyer   mode: solo
      acceptance: договор проверен
""",
        encoding="utf-8",
    )

    task = next_local_task(tasks, role="lawyer", brain_path=brain)

    assert task is not None
    assert task.task_id == "local-001"


# --- depends_on tests ---

def test_parse_local_tasks_extracts_depends_on_forward_reference(tmp_path):
    """depends_on can reference tasks defined later in the file."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-b - Second task
      role: developer
      depends_on: [task-a]
      acceptance: Done after task-a.

- [ ] [P1] task-a - First task
      role: developer
      acceptance: First task done.
""",
        encoding="utf-8",
    )

    parsed = parse_local_tasks(tasks)
    task_b = next(t for t in parsed if t.task_id == "task-b")
    task_a = next(t for t in parsed if t.task_id == "task-a")

    assert task_b.depends_on == ("task-a",)
    assert task_a.depends_on == ()


def test_parse_local_tasks_depends_on_missing_dependency_raises(tmp_path):
    """Missing dependency (not in file) raises precise error at parse time."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-a - First task
      role: developer
      depends_on: [task-x]
      acceptance: Depends on missing task-x.
""",
        encoding="utf-8",
    )

    try:
        parse_local_tasks(tasks)
    except ValueError as exc:
        assert "missing dependency" in str(exc).lower()
        assert "task-x" in str(exc)
    else:
        raise AssertionError("parse should have failed for missing dependency")


def test_parse_local_tasks_depends_on_bare_forms_parse(tmp_path):
    """Hand-written bare forms — a single id and a bare comma list — parse the
    same as the bracketed canonical form."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-x - X
      role: developer
      acceptance: done.

- [ ] [P1] task-y - Y
      role: developer
      acceptance: done.

- [ ] [P1] task-a - Bare single id
      role: developer
      depends_on: task-x
      acceptance: after x.

- [ ] [P1] task-b - Bare comma list
      role: developer
      depends_on: task-x, task-y
      acceptance: after x and y.
""",
        encoding="utf-8",
    )

    parsed = {t.task_id: t for t in parse_local_tasks(tasks)}
    assert parsed["task-a"].depends_on == ("task-x",)
    assert parsed["task-b"].depends_on == ("task-x", "task-y")


def test_parse_local_tasks_depends_on_unbalanced_bracket_raises(tmp_path):
    """An unbalanced bracket is a genuine malformed value and is rejected."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-a - First task
      role: developer
      depends_on: [task-x
      acceptance: Unbalanced bracket.
""",
        encoding="utf-8",
    )

    try:
        parse_local_tasks(tasks)
    except ValueError as exc:
        assert "unbalanced" in str(exc).lower() or "bracket" in str(exc).lower()
    else:
        raise AssertionError("parse should have failed for unbalanced bracket")


def test_parse_local_tasks_depends_on_bare_list_empty_component_raises(tmp_path):
    """Empty components are rejected in a bare list too, not only bracketed."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-a - First task
      role: developer
      depends_on: task-x,,task-y
      acceptance: Empty component.
""",
        encoding="utf-8",
    )

    try:
        parse_local_tasks(tasks)
    except ValueError as exc:
        assert "empty component" in str(exc).lower()
    else:
        raise AssertionError("parse should have failed for empty component")


def test_parse_local_tasks_depends_on_duplicate_ids_raises(tmp_path):
    """Duplicate dependency IDs raise precise error."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-a - First task
      role: developer
      depends_on: [task-x, task-x]
      acceptance: Duplicate deps.
- [ ] [P1] task-x - Dependency
      role: developer
      acceptance: Exists.
""",
        encoding="utf-8",
    )

    try:
        parse_local_tasks(tasks)
    except ValueError as exc:
        assert "duplicate" in str(exc).lower()
        assert "task-x" in str(exc)
    else:
        raise AssertionError("parse should have failed for duplicate dependencies")


def test_parse_local_tasks_depends_on_self_dependency_raises(tmp_path):
    """Self-dependency raises precise error."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-a - First task
      role: developer
      depends_on: [task-a]
      acceptance: Self dependency.
""",
        encoding="utf-8",
    )

    try:
        parse_local_tasks(tasks)
    except ValueError as exc:
        assert "self" in str(exc).lower()
        assert "task-a" in str(exc)
    else:
        raise AssertionError("parse should have failed for self-dependency")


def test_parse_local_tasks_depends_on_cycle_raises(tmp_path):
    """Cycle in dependencies raises precise error."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-a - First task
      role: developer
      depends_on: [task-b]
      acceptance: Depends on b.
- [ ] [P1] task-b - Second task
      role: developer
      depends_on: [task-a]
      acceptance: Depends on a.
""",
        encoding="utf-8",
    )

    try:
        parse_local_tasks(tasks)
    except ValueError as exc:
        assert "cycle" in str(exc).lower()
    else:
        raise AssertionError("parse should have failed for dependency cycle")


def test_parse_local_tasks_depends_on_three_node_cycle_raises(tmp_path):
    """A→B→C→A is rejected the same way as a two-node cycle."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-a - A
      role: developer
      depends_on: [task-b]
      acceptance: A.
- [ ] [P1] task-b - B
      role: developer
      depends_on: [task-c]
      acceptance: B.
- [ ] [P1] task-c - C
      role: developer
      depends_on: [task-a]
      acceptance: C.
""",
        encoding="utf-8",
    )

    try:
        parse_local_tasks(tasks)
    except ValueError as exc:
        assert "cycle" in str(exc).lower()
    else:
        raise AssertionError("parse should have failed for three-node cycle")


def test_parse_local_tasks_diamond_depends_on_is_not_a_cycle(tmp_path):
    """A diamond (C→A, C→B, A and B independent) is a DAG, not a cycle."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [x] [P1] task-a - A
      role: developer
      acceptance: A.
- [x] [P1] task-b - B
      role: developer
      acceptance: B.
- [ ] [P1] task-c - C
      role: developer
      depends_on: [task-a, task-b]
      acceptance: C.
""",
        encoding="utf-8",
    )

    parsed = parse_local_tasks(tasks)
    task_c = next(t for t in parsed if t.task_id == "task-c")
    assert task_c.depends_on == ("task-a", "task-b")


def test_next_local_task_skips_open_task_with_unmet_dependency(tmp_path):
    """next_local_task skips open tasks whose deps are not all done."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-b - Second task
      role: developer
      depends_on: [task-a]
      acceptance: Depends on task-a.

- [ ] [P1] task-a - First task
      role: developer
      acceptance: First task done.
""",
        encoding="utf-8",
    )

    # task-b depends on task-a which is open, so task-b should be skipped
    # task-a has no deps, should be returned
    task = next_local_task(tasks, role="developer")
    assert task is not None
    assert task.task_id == "task-a"


@pytest.mark.parametrize("dep_mark,dep_state", [
    ("~", "in-progress"),
    ("!", "blocked"),
])
def test_next_local_task_skips_when_dependency_is_not_done(tmp_path, dep_mark, dep_state):
    """Only [x] satisfies a dependency; in-progress and blocked do not."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        f"""# Local Tasks

- [{dep_mark}] [P1] task-a - First task
      role: developer
      acceptance: First task {dep_state}.

- [ ] [P1] task-b - Second task
      role: developer
      depends_on: [task-a]
      acceptance: Depends on task-a.
""",
        encoding="utf-8",
    )

    assert next_local_task(tasks, role="developer") is None


def test_next_local_task_returns_task_when_deps_are_done(tmp_path):
    """next_local_task returns task when all dependencies are done."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [x] [P1] task-a - First task
      role: developer
      acceptance: First task done.

- [ ] [P1] task-b - Second task
      role: developer
      depends_on: [task-a]
      acceptance: Depends on task-a.
""",
        encoding="utf-8",
    )

    # task-a is done, so task-b should be available
    task = next_local_task(tasks, role="developer")
    assert task is not None
    assert task.task_id == "task-b"


def test_next_local_task_dependency_order_in_file_irrelevant(tmp_path):
    """Dependency order in file doesn't matter; topological availability does."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-c - Third task
      role: developer
      depends_on: [task-b]
      acceptance: Depends on task-b.

- [x] [P1] task-a - First task
      role: developer
      acceptance: Done.

- [ ] [P1] task-b - Second task
      role: developer
      depends_on: [task-a]
      acceptance: Depends on task-a.
""",
        encoding="utf-8",
    )

    # task-a is done, task-b depends on task-a (done), task-c depends on task-b (open)
    # Should return task-b first
    task = next_local_task(tasks, role="developer")
    assert task is not None
    assert task.task_id == "task-b"


def test_take_local_task_rejects_unmet_dependency_no_mutation(tmp_path):
    """take_local_task rejects task with unmet deps before any mutation."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    (workspace / "TASKS.md").write_text(
        """# Local Tasks

- [ ] [P1] task-b - Second task
      role: developer
      depends_on: [task-a]
      acceptance: Depends on task-a.

- [ ] [P1] task-a - First task
      role: developer
      acceptance: First task done.
""",
        encoding="utf-8",
    )
    (workspace / "LOG.md").write_text("# Local Log\n", encoding="utf-8")

    try:
        take_local_task(workspace, "task-b", "agent-a")
    except ValueError as exc:
        assert "dependenc" in str(exc).lower() or "unmet" in str(exc).lower()
    else:
        raise AssertionError("take should have failed for unmet dependency")

    # Verify no mutation occurred
    content = (workspace / "TASKS.md").read_text(encoding="utf-8")
    assert "- [ ] [P1] task-b" in content
    assert "started:" not in content
    assert "by: agent-a" not in content
    log_content = (workspace / "LOG.md").read_text(encoding="utf-8")
    assert "took task-b" not in log_content


def test_complete_local_task_rejects_unmet_dependency_no_mutation(tmp_path):
    """complete_local_task rejects task with unmet deps before any mutation."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    (workspace / "TASKS.md").write_text(
        """# Local Tasks

- [~] [P1] task-b - Second task
      role: developer
      depends_on: [task-a]
      acceptance: Depends on task-a.
      started: 2026-08-14T10:00:00Z
      by: agent-a

- [ ] [P1] task-a - First task
      role: developer
      acceptance: First task done.
""",
        encoding="utf-8",
    )
    (workspace / "LOG.md").write_text("# Local Log\n", encoding="utf-8")

    try:
        complete_local_task(workspace, "task-b", "agent-a", "openai-gpt-5.4", "done")
    except ValueError as exc:
        assert "dependenc" in str(exc).lower() or "unmet" in str(exc).lower()
    else:
        raise AssertionError("complete should have failed for unmet dependency")

    # Verify no mutation occurred
    content = (workspace / "TASKS.md").read_text(encoding="utf-8")
    assert "- [~] [P1] task-b" in content
    assert "model: openai-gpt-5.4" not in content
    assert "completed:" not in content
    log_content = (workspace / "LOG.md").read_text(encoding="utf-8")
    assert "completed task-b" not in log_content


def test_take_local_task_succeeds_when_deps_met(tmp_path):
    """take_local_task succeeds when all dependencies are done."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    (workspace / "TASKS.md").write_text(
        """# Local Tasks

- [x] [P1] task-a - First task
      role: developer
      acceptance: First task done.
      model: openai-gpt-5.4
      completed: 2026-08-14T10:00:00Z
      by: agent-x

- [ ] [P1] task-b - Second task
      role: developer
      depends_on: [task-a]
      acceptance: Depends on task-a.
""",
        encoding="utf-8",
    )
    (workspace / "LOG.md").write_text("# Local Log\n", encoding="utf-8")

    task = take_local_task(workspace, "task-b", "agent-a")

    assert task.task_id == "task-b"
    assert task.state == "in-progress"
    content = (workspace / "TASKS.md").read_text(encoding="utf-8")
    assert "- [~] [P1] task-b" in content
    assert "started:" in content
    assert "by: agent-a" in content


def test_complete_local_task_succeeds_when_deps_met(tmp_path):
    """complete_local_task succeeds when all dependencies are done."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    (workspace / "TASKS.md").write_text(
        """# Local Tasks

- [x] [P1] task-a - First task
      role: developer
      acceptance: First task done.
      model: openai-gpt-5.4
      completed: 2026-08-14T10:00:00Z
      by: agent-x

- [~] [P1] task-b - Second task
      role: developer
      depends_on: [task-a]
      acceptance: Depends on task-a.
      started: 2026-08-14T11:00:00Z
      by: agent-a
""",
        encoding="utf-8",
    )
    (workspace / "LOG.md").write_text("# Local Log\n", encoding="utf-8")

    task = complete_local_task(workspace, "task-b", "agent-a", "openai-gpt-5.4", "done")

    assert task.state == "done"
    content = (workspace / "TASKS.md").read_text(encoding="utf-8")
    assert "- [x] [P1] task-b" in content
    assert "model: openai-gpt-5.4" in content
    assert "completed:" in content


def test_next_local_task_skips_already_done_task(tmp_path):
    """next never returns an already-done task, even when its deps are met."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [x] [P1] task-a - First task
      role: developer
      acceptance: First task done.

- [x] [P1] task-b - Second task
      role: developer
      depends_on: [task-a]
      acceptance: Already done.
""",
        encoding="utf-8",
    )

    assert next_local_task(tasks, role="developer") is None


def test_take_local_task_rejects_already_done_no_mutation(tmp_path):
    """take of an already-done task is rejected before any mutation."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    tasks_text = """# Local Tasks

- [x] [P1] task-a - First task
      role: developer
      acceptance: First task done.
      model: openai-gpt-5.4
      completed: 2026-08-14T10:00:00Z
      by: agent-x

- [x] [P1] task-b - Second task
      role: developer
      depends_on: [task-a]
      acceptance: Already done.
      model: openai-gpt-5.4
      completed: 2026-08-14T11:00:00Z
      by: agent-a
"""
    (workspace / "TASKS.md").write_text(tasks_text, encoding="utf-8")
    (workspace / "LOG.md").write_text("# Local Log\n", encoding="utf-8")

    try:
        take_local_task(workspace, "task-b", "agent-b")
    except ValueError as exc:
        assert "expected state open" in str(exc)
    else:
        raise AssertionError("take of already-done task unexpectedly succeeded")

    assert (workspace / "TASKS.md").read_text(encoding="utf-8") == tasks_text
    assert "took task-b" not in (workspace / "LOG.md").read_text(encoding="utf-8")


def test_complete_local_task_already_done_is_idempotent_when_deps_met(tmp_path):
    """complete of an already-done task with matching owner+model is a no-op."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    tasks_text = """# Local Tasks

- [x] [P1] task-a - First task
      role: developer
      acceptance: First task done.
      model: openai-gpt-5.4
      completed: 2026-08-14T10:00:00Z
      by: agent-x

- [x] [P1] task-b - Second task
      role: developer
      depends_on: [task-a]
      acceptance: Already done.
      started: 2026-08-14T11:00:00Z
      by: agent-a
      model: openai-gpt-5.4
      completed: 2026-08-14T12:00:00Z
"""
    log_text = "# Local Log\n"
    (workspace / "TASKS.md").write_text(tasks_text, encoding="utf-8")
    (workspace / "LOG.md").write_text(log_text, encoding="utf-8")

    task = complete_local_task(workspace, "task-b", "agent-a", "openai-gpt-5.4", "done again")

    assert task.state == "done"
    assert task.task_id == "task-b"
    assert (workspace / "TASKS.md").read_text(encoding="utf-8") == tasks_text
    assert (workspace / "LOG.md").read_text(encoding="utf-8") == log_text
    assert not (workspace / ".workspace-queue-journal.json").exists()


def test_complete_local_task_rejects_already_done_with_unmet_deps(tmp_path):
    """complete stays fail-closed on unmet deps even if the task is already [x]."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    tasks_text = """# Local Tasks

- [ ] [P1] task-a - First task
      role: developer
      acceptance: First task still open.

- [x] [P1] task-b - Second task
      role: developer
      depends_on: [task-a]
      acceptance: Inconsistent already-done.
      started: 2026-08-14T11:00:00Z
      by: agent-a
      model: openai-gpt-5.4
      completed: 2026-08-14T12:00:00Z
"""
    (workspace / "TASKS.md").write_text(tasks_text, encoding="utf-8")
    (workspace / "LOG.md").write_text("# Local Log\n", encoding="utf-8")

    try:
        complete_local_task(workspace, "task-b", "agent-a", "openai-gpt-5.4", "done")
    except ValueError as exc:
        assert "dependenc" in str(exc).lower() or "unmet" in str(exc).lower()
        assert "task-a" in str(exc)
    else:
        raise AssertionError("complete of already-done task with unmet deps succeeded")

    assert (workspace / "TASKS.md").read_text(encoding="utf-8") == tasks_text
    assert "done" not in (workspace / "LOG.md").read_text(encoding="utf-8")


def test_take_and_complete_reject_when_one_of_several_deps_unmet(tmp_path):
    """A task with two deps is unavailable until every listed dependency is [x]."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    tasks_text = """# Local Tasks

- [x] [P1] task-a - First
      role: developer
      acceptance: Done.

- [ ] [P1] task-b - Second
      role: developer
      acceptance: Still open.

- [ ] [P1] task-c - Third
      role: developer
      depends_on: [task-a, task-b]
      acceptance: Needs both.
"""
    (workspace / "TASKS.md").write_text(tasks_text, encoding="utf-8")
    (workspace / "LOG.md").write_text("# Local Log\n", encoding="utf-8")

    assert next_local_task(workspace / "TASKS.md", role="developer").task_id == "task-b"

    try:
        take_local_task(workspace, "task-c", "agent-a")
    except ValueError as exc:
        assert "dependenc" in str(exc).lower()
        assert "task-b" in str(exc)
    else:
        raise AssertionError("take should have failed while task-b is open")

    assert (workspace / "TASKS.md").read_text(encoding="utf-8") == tasks_text


def test_recover_workspace_transaction_preserves_depends_on(tmp_path):
    """Journal recovery preserves depends_on field."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tasks_path = workspace / "TASKS.md"
    log_path = workspace / "LOG.md"
    tasks_before = """# Local Tasks

- [x] [P1] task-x - Dependency task
      role: developer
      acceptance: Done.
      model: openai-gpt-5.4
      completed: 2026-08-14T09:00:00Z
      by: agent-y

- [ ] [P1] task-a - First task
      role: developer
      depends_on: [task-x]
      acceptance: Depends on x.
"""
    tasks_after = """# Local Tasks

- [x] [P1] task-x - Dependency task
      role: developer
      acceptance: Done.
      model: openai-gpt-5.4
      completed: 2026-08-14T09:00:00Z
      by: agent-y

- [~] [P1] task-a - First task
      role: developer
      depends_on: [task-x]
      acceptance: Depends on x.
      started: 2026-08-14T10:00:00Z
      by: agent-a
"""
    log_before = "# Local Log\n"
    log_after = """# Local Log

## 2026-08-14T10:00:00Z | agent-a | took task-a

- Moved task-a to in-progress.
"""
    tasks_path.write_text(tasks_after, encoding="utf-8")
    log_path.write_text(log_before, encoding="utf-8")

    import brain_workspace as _W
    _W._write_workspace_journal(
        workspace,
        operation="take",
        task_id="task-a",
        tasks_before=tasks_before,
        log_before=log_before,
        tasks_after=tasks_after,
        log_after=log_after,
    )

    _W._recover_workspace_transaction(workspace)

    assert tasks_path.read_text(encoding="utf-8") == tasks_after
    assert log_path.read_text(encoding="utf-8") == log_after
    assert not (workspace / ".workspace-queue-journal.json").exists()

    # Verify depends_on is preserved in parsed task
    recovered = parse_local_tasks(tasks_path)
    task_a = next(t for t in recovered if t.task_id == "task-a")
    assert task_a.depends_on == ("task-x",)


# --- Issue 1: depends_on must be found regardless of position among multiple fields ---

def test_parse_local_tasks_depends_on_not_at_line_start(tmp_path):
    """depends_on found when not at line start (multiple fields on one line)."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-b - Second task
      role: developer   depends_on: [task-a]   acceptance: Done after task-a.

- [ ] [P1] task-a - First task
      role: developer
      acceptance: First task done.
""",
        encoding="utf-8",
    )

    parsed = parse_local_tasks(tasks)
    task_b = next(t for t in parsed if t.task_id == "task-b")
    task_a = next(t for t in parsed if t.task_id == "task-a")

    assert task_b.depends_on == ("task-a",)
    assert task_a.depends_on == ()


def test_parse_local_tasks_depends_on_multiple_fields_various_orders(tmp_path):
    """depends_on parsed correctly in various field orders on same line."""
    for fields_line in (
        "      depends_on: [task-a]   role: developer   acceptance: After a.",
        "      role: developer   depends_on: [task-a]   acceptance: After a.",
        "      acceptance: After a.   depends_on: [task-a]   role: developer",
        "      role: developer   acceptance: After a.   depends_on: [task-a]",
    ):
        tasks = tmp_path / "TASKS.md"
        tasks.write_text(
            f"""# Local Tasks

- [ ] [P1] task-b - Second task
{fields_line}

- [ ] [P1] task-a - First task
      role: developer
      acceptance: First task done.
""",
            encoding="utf-8",
        )

        parsed = parse_local_tasks(tasks)
        task_b = next(t for t in parsed if t.task_id == "task-b")
        assert task_b.depends_on == ("task-a",), f"Failed for line: {fields_line}"
        assert task_b.role == "developer"
        assert task_b.acceptance == "After a."


# --- Issue 1b: Reject duplicate depends_on fields ---

def test_parse_local_tasks_rejects_duplicate_depends_on_fields(tmp_path):
    """Duplicate depends_on fields on same task raise precise error."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-a - First task
      role: developer
      depends_on: [task-x]
      depends_on: [task-y]
      acceptance: Duplicate depends_on fields.
- [ ] [P1] task-x - Dep X
      role: developer
      acceptance: Exists.
- [ ] [P1] task-y - Dep Y
      role: developer
      acceptance: Exists.
""",
        encoding="utf-8",
    )

    try:
        parse_local_tasks(tasks)
    except ValueError as exc:
        assert "duplicate depends_on" in str(exc).lower()
    else:
        raise AssertionError("parse should have failed for duplicate depends_on fields")


@pytest.mark.parametrize("fields_line", [
    # Same continuation line, depends_on repeated at various positions
    "      depends_on: [task-x]   depends_on: [task-y]   role: developer",
    "      role: developer   depends_on: [task-x]   depends_on: [task-y]",
    "      role: developer   depends_on: [task-x]   acceptance: Done.   depends_on: [task-y]",
    "      depends_on: [task-x]   role: developer   depends_on: [task-y]   acceptance: Done.",
])
def test_parse_local_tasks_rejects_duplicate_depends_on_on_same_line(tmp_path, fields_line):
    """Duplicate depends_on on the same continuation line must be rejected.

    grammar.parse_fields returns a dict and silently drops repeated fields, so
    this must be detected before the dict collapses them. Rejection must hold
    for arbitrary field order on the line.
    """
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        f"""# Local Tasks

- [ ] [P1] task-a - First task
{fields_line}
      acceptance: Duplicate depends_on on one line.
- [ ] [P1] task-x - Dep X
      role: developer
      acceptance: Exists.
- [ ] [P1] task-y - Dep Y
      role: developer
      acceptance: Exists.
""",
        encoding="utf-8",
    )

    try:
        parse_local_tasks(tasks)
    except ValueError as exc:
        assert "duplicate depends_on" in str(exc).lower()
    else:
        raise AssertionError(f"parse should have failed for duplicate depends_on on same line: {fields_line}")


def test_parse_local_tasks_rejects_duplicate_depends_on_across_lines(tmp_path):
    """Duplicate depends_on spread across separate continuation lines rejected."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-a - First task
      role: developer
      depends_on: [task-x]
      acceptance: First.
      depends_on: [task-y]
- [ ] [P1] task-x - Dep X
      role: developer
      acceptance: Exists.
- [ ] [P1] task-y - Dep Y
      role: developer
      acceptance: Exists.
""",
        encoding="utf-8",
    )

    try:
        parse_local_tasks(tasks)
    except ValueError as exc:
        assert "duplicate depends_on" in str(exc).lower()
    else:
        raise AssertionError("parse should have failed for duplicate depends_on across lines")


# --- Round 3 HIGH 1: same-line duplicate detector must not false-positive on
# --- prose/backticked mentions of depends_on, while still rejecting two real
# --- fields in any order. Uses the shared duplicate-aware grammar.
def test_duplicate_depends_on_detector_ignores_prose_and_backticked_mentions(tmp_path):
    """A line carrying one real depends_on plus prose/backticked mentions must
    be accepted; only true parsed field starts count toward duplication."""
    cases = [
        # prose mention inside the acceptance value
        "      role: developer   depends_on: [task-a]   acceptance: use depends_on: [task-a] in prose",
        # prose mention at the very start of a value
        "      acceptance: depends_on: [task-a] is the syntax   role: developer   depends_on: [task-a]",
        # backticked mention without a two-space field boundary inside the span
        "      role: developer   depends_on: [task-a]   acceptance: write `depends_on: [task-a]` verbatim",
        # two-space field-like text inside inline code must not split or duplicate
        "      role: developer   depends_on: [task-a]   acceptance: write `role: developer   depends_on: [task-a]` verbatim",
        "      acceptance: see `role: x   depends_on: [a]   mode: solo`   depends_on: [task-a]   role: developer",
    ]
    for fields_line in cases:
        tasks = tmp_path / "TASKS.md"
        tasks.write_text(
            f"""# Local Tasks

- [ ] [P1] task-b - Second task
{fields_line}

- [ ] [P1] task-a - First task
      role: developer
      acceptance: First task done.
""",
            encoding="utf-8",
        )
        parsed = parse_local_tasks(tasks)
        task_b = next(t for t in parsed if t.task_id == "task-b")
        assert task_b.depends_on == ("task-a",), f"Failed for line: {fields_line}"
        assert task_b.depends_on is not None


@pytest.mark.parametrize("fields_line", [
    "      role: developer   depends_on: [task-x]   depends_on: [task-y]",
    "      depends_on: [task-x]   role: developer   depends_on: [task-y]   acceptance: Done.",
    "      acceptance: Done.   depends_on: [task-x]   role: developer   depends_on: [task-y]",
    "      depends_on: [task-x]   depends_on: [task-y]   role: developer",
])
def test_duplicate_depends_on_detector_rejects_two_real_fields_any_order(tmp_path, fields_line):
    """Two genuine depends_on fields on one line are rejected regardless of order."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        f"""# Local Tasks

- [ ] [P1] task-b - Second task
{fields_line}

- [ ] [P1] task-x - Dep X
      role: developer
      acceptance: Exists.
- [ ] [P1] task-y - Dep Y
      role: developer
      acceptance: Exists.
""",
        encoding="utf-8",
    )
    try:
        parse_local_tasks(tasks)
    except ValueError as exc:
        assert "duplicate depends_on" in str(exc).lower()
    else:
        raise AssertionError(f"should reject two real depends_on fields: {fields_line}")


# --- Issue 1c: Reject empty comma components in depends_on ---

@pytest.mark.parametrize("bad_list", [
    "[,]",           # only empty
    "[task-a,]",     # trailing comma
    "[,task-a]",     # leading comma
    "[task-a,,task-b]",  # double comma
    "[task-a, ,task-b]", # space-only component
])
def test_parse_local_tasks_rejects_empty_depends_on_components(tmp_path, bad_list):
    """Empty comma components in depends_on raise precise error."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        f"""# Local Tasks

- [ ] [P1] task-a - First task
      role: developer
      depends_on: {bad_list}
      acceptance: Bad list.
""",
        encoding="utf-8",
    )

    try:
        parse_local_tasks(tasks)
    except ValueError as exc:
        assert "empty" in str(exc).lower() or "component" in str(exc).lower()
    else:
        raise AssertionError(f"parse should have failed for empty component in {bad_list}")


def test_parse_local_tasks_empty_depends_on_list_is_valid(tmp_path):
    """depends_on: [] means no dependencies; the task is available."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-a - First task
      role: developer
      depends_on: []
      acceptance: No dependencies.
""",
        encoding="utf-8",
    )

    parsed = parse_local_tasks(tasks)
    assert parsed[0].depends_on == ()
    assert next_local_task(tasks, role="developer").task_id == "task-a"


# --- Issue 2: Reject duplicate task IDs deterministically ---

def test_parse_local_tasks_rejects_duplicate_task_ids(tmp_path):
    """Duplicate task IDs in file raise precise error before any graph ops."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-a - First task
      role: developer
      acceptance: First.

- [ ] [P1] task-a - Duplicate task
      role: developer
      acceptance: Second.
""",
        encoding="utf-8",
    )

    try:
        parse_local_tasks(tasks)
    except ValueError as exc:
        assert "duplicate task id" in str(exc).lower()
        assert "task-a" in str(exc)
    else:
        raise AssertionError("parse should have failed for duplicate task IDs")


def test_parse_local_tasks_duplicate_ids_rejected_before_depends_on_validation(tmp_path):
    """Duplicate IDs caught first, before depends_on validation runs."""
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        """# Local Tasks

- [ ] [P1] task-a - First task
      role: developer
      depends_on: [missing-task]
      acceptance: Has missing dep.

- [ ] [P1] task-a - Duplicate task
      role: developer
      acceptance: Second.
""",
        encoding="utf-8",
    )

    try:
        parse_local_tasks(tasks)
    except ValueError as exc:
        # Should fail on duplicate ID, not missing dependency
        assert "duplicate task id" in str(exc).lower()
        assert "task-a" in str(exc)
    else:
        raise AssertionError("parse should have failed for duplicate task IDs first")


# --- Issue 3: Deterministic concurrency via ordered_lock ---
#
# ordered_lock installs a *wrapper* around the workspace queue lock so a test
# can force a known entry order between two threads. The only thing a scenario
# varies between its two runs is ``inner_factory``: the real ``_queue_lock``
# (a mutex) on one side, a bare nullcontext on the other. The orchestration is
# otherwise identical — the driver observes whether the second thread actually
# *entered* its inner context (which is decided by the lock itself: a real mutex
# keeps the second out until the first exits; a nullcontext admits it at once)
# and adapts one bounded release accordingly. Each scenario runs twice and
# asserts the two orderings differ. No sleeps, barriers or scheduling luck are
# involved: the wrapper gates on Events with bounded timeouts only.


@contextmanager
def _ordered_lock(workspace, inner_factory, first_name,
                  first_entered, release_first, second_attempted, second_entered):
    """Force a deterministic entry order for the workspace lock.

    * a thread whose name == *first_name*: signal ``first_entered``, block on
      ``release_first`` (bounded timeout), then yield inside the inner context;
    * any other thread: signal ``second_attempted`` *before* it tries to acquire
      (it will block there on a real mutex), then signal ``second_entered`` from
      *inside* the inner context (i.e. only once it has actually entered).
    """
    if threading.current_thread().name == first_name:
        with inner_factory(workspace):
            first_entered.set()
            if not release_first.wait(timeout=10.0):
                raise RuntimeError("ordered_lock timed out waiting to release first thread")
            yield
    else:
        second_attempted.set()
        with inner_factory(workspace):
            second_entered.set()
            yield


_TASKS_TEMPLATE = (
    "# Local Tasks\n"
    "\n"
    "- [~] [P1] task-a - First task\n"
    "      role: developer\n"
    "      acceptance: First task done.\n"
    "      started: 2026-08-14T10:00:00Z\n"
    "      by: agent-a\n"
    "\n"
    "- [ ] [P1] task-b - Second task\n"
    "      role: developer\n"
    "      depends_on: [task-a]\n"
    "      acceptance: Depends on task-a.\n"
)


def _dep_workspace(tmp_path, label="workspace"):
    """task-a is already in-progress (owned by agent-a); task-b depends on it."""
    workspace = tmp_path / label
    workspace.mkdir()
    (workspace / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")
    (workspace / "TASKS.md").write_text(_TASKS_TEMPLATE, encoding="utf-8")
    (workspace / "LOG.md").write_text("# Local Log\n", encoding="utf-8")
    return workspace


def _run_ordered_pair(monkeypatch, workspace, *, null, first_op, second_op):
    """Start two threads in forced order; return ``(results, overtook)``.

    `overtook` is True exactly when the second thread entered its inner context
    *before* the first was released. A real ``_queue_lock`` mutex cannot let a
    second thread in until the first exits, so `overtook` is False; a bare
    nullcontext admits the second at once, so `overtook` is True. The scenario
    only varies ``inner_factory`` (real mutex vs nullcontext) and otherwise
    follows one adaptive path: it watches how far the second thread got in a
    bounded 0.1s window instead of branching on the ``*null*`` flag. ``second_
    attempted`` (set before acquisition) gates the wait; ``second_entered``
    (set inside the inner context) tells us the second truly got in and
    overtook. Release and bounded joins always run under ``finally``, so a
    failed assertion never leaks a thread or a held lock.
    """
    real_inner = _W._queue_lock
    inner_factory = (lambda ws: nullcontext()) if null else real_inner

    first_entered = threading.Event()
    release_first = threading.Event()
    second_attempted = threading.Event()
    second_entered = threading.Event()
    first_done = threading.Event()
    second_done = threading.Event()
    results = {}

    def worker(name, op, done):
        try:
            results[name] = op()
        except Exception as exc:  # noqa: BLE001 - captured for assertion
            results[name] = exc
        finally:
            done.set()

    def replacement(ws):
        return _ordered_lock(
            ws, inner_factory, "first",
            first_entered, release_first, second_attempted, second_entered,
        )

    monkeypatch.setattr(_W, "_queue_lock", replacement)

    first = threading.Thread(
        target=worker, args=("first", first_op, first_done), name="first")
    second = threading.Thread(
        target=worker, args=("second", second_op, second_done), name="second")

    first.start()
    try:
        if not first_entered.wait(timeout=10.0):
            raise AssertionError("first thread never entered the lock")
        second.start()
        if not second_attempted.wait(timeout=10.0):
            raise AssertionError("second thread never attempted the lock")
        # One adaptive path: a real mutex cannot admit the second inside the
        # 0.1s window (it is excluded until the first exits); a nullcontext can.
        overtook = second_entered.wait(timeout=0.1)
        if overtook and not second_done.wait(timeout=10.0):
            raise AssertionError("second inner op did not finish before the first was released")
    finally:
        release_first.set()
        first.join(timeout=10.0)
        second.join(timeout=10.0)

    if first.is_alive() or second.is_alive():
        raise AssertionError("ordered threads did not finish cleanly")
    if not (first_done.is_set() and second_done.is_set()):
        raise AssertionError("ordered threads did not signal completion")
    return results, overtook


def _log_summaries(workspace):
    return [e.summary for e in _W.parse_local_log_entries(workspace / "LOG.md", limit=16)]


def _assert_no_journal(workspace):
    assert not (workspace / ".workspace-queue-journal.json").exists()


def _task(workspace, task_id):
    return next(t for t in _W.parse_local_tasks(workspace / "TASKS.md") if t.task_id == task_id)


def _raw_field(workspace, task_id, name):
    """Raw ``name:`` field recorded on the given task's block in TASKS.md."""
    lines = (workspace / "TASKS.md").read_text(encoding="utf-8").splitlines()
    in_block = False
    for line in lines:
        match = _W.TASK_RE.match(line.rstrip())
        if match:
            in_block = match.group("task_id") == task_id
            continue
        stripped = line.lstrip()
        if in_block and stripped.startswith(f"{name}:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _assert_owner_started(workspace, *, task_b_taken):
    """Exact raw owner ('by:') and 'started' fields where applicable."""
    assert _raw_field(workspace, "task-a", "by") == "agent-a"
    assert _raw_field(workspace, "task-a", "completed") != ""
    if task_b_taken:
        assert _raw_field(workspace, "task-b", "by") == "agent-b"
        assert _raw_field(workspace, "task-b", "started").endswith("Z")
    else:
        assert _raw_field(workspace, "task-b", "by") == ""
        assert _raw_field(workspace, "task-b", "started") == ""


def test_ordered_lock_completion_first_real_lock(tmp_path, monkeypatch):
    """Completion-first under the real lock: first completes task-a, so the
    second take-b runs after the dependency is done and succeeds. The mutex
    excludes the second, so it never overtakes."""
    ws = _dep_workspace(tmp_path)
    results, overtook = _run_ordered_pair(
        monkeypatch, ws, null=False,
        first_op=lambda: _W.complete_local_task(ws, "task-a", "agent-a", "openai-gpt-5.4", "done a"),
        second_op=lambda: _W.take_local_task(ws, "task-b", "agent-b"),
    )
    assert overtook is False
    assert not isinstance(results["first"], Exception)
    assert not isinstance(results["second"], Exception), results["second"]
    assert _task(ws, "task-a").state == "done"
    assert _task(ws, "task-b").state == "in-progress"
    assert _task(ws, "task-b").depends_on == ("task-a",)
    assert _log_summaries(ws) == ["done a", "took task-b"]
    _assert_owner_started(ws, task_b_taken=True)
    _assert_no_journal(ws)


def test_ordered_lock_completion_first_nullcontext(tmp_path, monkeypatch):
    """Completion-first under nullcontext: the second take-b overtakes while
    task-a is still in-progress, so it rejects with unmet dependencies."""
    ws = _dep_workspace(tmp_path)
    results, overtook = _run_ordered_pair(
        monkeypatch, ws, null=True,
        first_op=lambda: _W.complete_local_task(ws, "task-a", "agent-a", "openai-gpt-5.4", "done a"),
        second_op=lambda: _W.take_local_task(ws, "task-b", "agent-b"),
    )
    assert overtook is True
    assert isinstance(results["second"], ValueError), results["second"]
    assert "dependenc" in str(results["second"]).lower()
    assert not isinstance(results["first"], Exception)
    assert _task(ws, "task-a").state == "done"
    assert _task(ws, "task-b").state == "open"
    assert _log_summaries(ws) == ["done a"]
    _assert_owner_started(ws, task_b_taken=False)
    _assert_no_journal(ws)


def test_ordered_lock_take_first_real_lock(tmp_path, monkeypatch):
    """Take-first under the real lock: the first take-b runs while task-a is
    still in-progress, so it rejects; the second complete-a then succeeds. The
    mutex excludes the second, so it never overtakes."""
    ws = _dep_workspace(tmp_path)
    results, overtook = _run_ordered_pair(
        monkeypatch, ws, null=False,
        first_op=lambda: _W.take_local_task(ws, "task-b", "agent-b"),
        second_op=lambda: _W.complete_local_task(ws, "task-a", "agent-a", "openai-gpt-5.4", "done a"),
    )
    assert overtook is False
    assert isinstance(results["first"], ValueError), results["first"]
    assert "dependenc" in str(results["first"]).lower()
    assert not isinstance(results["second"], Exception)
    assert _task(ws, "task-a").state == "done"
    assert _task(ws, "task-b").state == "open"
    assert _log_summaries(ws) == ["done a"]
    _assert_owner_started(ws, task_b_taken=False)
    _assert_no_journal(ws)


def test_ordered_lock_take_first_nullcontext(tmp_path, monkeypatch):
    """Take-first under nullcontext: the second complete-a overtakes (task-a
    becomes done), then the first take-b runs and succeeds."""
    ws = _dep_workspace(tmp_path)
    results, overtook = _run_ordered_pair(
        monkeypatch, ws, null=True,
        first_op=lambda: _W.take_local_task(ws, "task-b", "agent-b"),
        second_op=lambda: _W.complete_local_task(ws, "task-a", "agent-a", "openai-gpt-5.4", "done a"),
    )
    assert overtook is True
    assert not isinstance(results["first"], Exception), results["first"]
    assert not isinstance(results["second"], Exception)
    assert _task(ws, "task-a").state == "done"
    assert _task(ws, "task-b").state == "in-progress"
    assert _task(ws, "task-b").depends_on == ("task-a",)
    assert _log_summaries(ws) == ["done a", "took task-b"]
    _assert_owner_started(ws, task_b_taken=True)
    _assert_no_journal(ws)


# Shared field-start scanner coverage (inline-code masking, two-space
# boundary, unmatched backtick) lives in tests/python/test_task_grammar.py.
# Workspace-level acceptance of those lines is
# test_duplicate_depends_on_detector_ignores_prose_and_backticked_mentions.


# --- Issue 4/5: Documentation, template parity and installer packaging ---

def test_tasks_schema_documents_depends_on_syntax_and_fail_closed():
    """tasks/SCHEMA.md documents exact depends_on syntax and fail-closed
    next/take/complete semantics."""
    schema = (REPO / "tasks" / "SCHEMA.md").read_text(encoding="utf-8")
    assert "depends_on: [task-id-1, task-id-2" in schema
    assert "Пустые компоненты запрещены" in schema
    assert "только один раз" in schema
    assert "**строго отклоняет**" in schema
    assert "next_local_task" in schema
    assert "take_local_task" in schema
    assert "complete_local_task" in schema
    assert "не мутирует файлы" in schema.lower()
    assert "Пустой список `[]` допустим" in schema
    assert "уже `[x]`" in schema
    assert "идемпотентный no-op" in schema
    assert "inline code" in schema


def test_v2_tasks_schema_parity_with_tasks_schema():
    """runtime/templates/v2/tasks/SCHEMA.md must match tasks/SCHEMA.md so setup
    does not overwrite the new contract on the next run (setup-brain-v2.sh copies
    the v2 template over tasks/SCHEMA.md when they differ)."""
    v2 = (REPO / "runtime" / "templates" / "v2" / "tasks" / "SCHEMA.md").read_text(encoding="utf-8")
    live = (REPO / "tasks" / "SCHEMA.md").read_text(encoding="utf-8")
    assert v2 == live


def test_workspace_template_tasks_contract_documents_depends_on():
    """The folder-native workspace TASKS.md template ships the full depends_on
    contract (syntax + fail-closed semantics) that init-template writes into
    every new workspace, so a fresh workspace is self-documenting."""
    template = (REPO / "runtime" / "templates" / "workspace" / "TASKS.md").read_text(encoding="utf-8")
    # Exact syntax example present on a real task line.
    assert "depends_on: [local-001]" in template
    # Bracketed, comma-separated list form is spelled out.
    assert "depends_on: [task-id-1, task-id-2" in template
    # Empty components are rejected.
    assert "empty components are rejected" in template
    # Empty list is valid.
    assert "empty list [] is valid" in template
    # The field may appear only once; duplicates rejected.
    assert "may appear only once" in template
    # Fail-closed semantics: next skips; take/complete reject with no mutation.
    assert "next skips tasks not in [ ]" in template
    assert "take/complete reject unmet deps with no mutation" in template
    assert "already [x] is fail-closed" in template


def test_guide_documents_fail_closed_dependency_semantics():
    """spec/guide.md documents exact depends_on syntax and fail-closed
    next/take/complete behavior for folder-native workspaces."""
    guide = (REPO / "spec" / "guide.md").read_text(encoding="utf-8")
    assert "depends_on: [task-id-1, task-id-2" in guide
    assert "next_local_task" in guide
    assert "take_local_task" in guide
    assert "complete_local_task" in guide
    assert "empty list `[]` is valid" in guide
    assert "already `[x]`" in guide
    assert "idempotent no-op" in guide
    assert "inline code" in guide
