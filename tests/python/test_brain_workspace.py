from pathlib import Path
import os
import subprocess
import sys
import threading

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
