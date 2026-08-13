# Folder-native Workspaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working version where agents can safely work inside selected user folders using local `BRAIN.md`, optional local `TASKS.md` and optional local `LOG.md`.

**Architecture:** The folder remains the source of truth. Brain discovers folders by scanning approved roots for `BRAIN.md` and produces generated summaries, but does not maintain a hand-edited central registry. Runtime support is split into small parsing/discovery helpers, CLI commands, tests and documentation.

**Tech Stack:** Bash CLIs under `runtime/bin`, Python helpers under `runtime/lib`, pytest under `tests/python`, smoke cases under `tests/cases`, Markdown docs/templates.

---

## Pilot Roots

- `/path/to/workspace-alpha`
- `/path/to/workspace-beta`

Initial concrete workspace candidates:

- `/path/to/workspace-alpha`
- `/path/to/workspace-alpha/child`
- `/path/to/workspace-beta`
- `/path/to/workspace-beta/data-export`

Do not move, rename or delete files in these folders during MVP setup. Adding local Markdown control files requires explicit user approval because those folders are outside the Brain repo.

## File Structure

- Create: `runtime/templates/workspace/BRAIN.md`
  - Template for local folder purpose, rules, roles, sensitive zones and done checks.
- Create: `runtime/templates/workspace/TASKS.md`
  - Template for local folder tasks.
- Create: `runtime/templates/workspace/LOG.md`
  - Template for local folder audit log.
- Create: `runtime/lib/brain_workspace.py`
  - Pure Python helpers for marker discovery, local task parsing and local log parsing.
- Create: `runtime/bin/brain-workspace`
  - CLI entrypoint for `discover`, `summary`, `nearest` and `init-template`.
- Modify: `runtime/bin/brain-orchestrator`
  - Add dry-run support for workspace-scoped launch context if the current code path allows it without a large refactor.
- Modify: `runtime/bin/brain-status`
  - Add optional workspace summary only after discovery helpers are stable.
- Modify: `runtime/mcp/server.py` and `runtime/mcp/tools_misc.py`
  - Expose read-only workspace discovery tools only after CLI behavior is tested.
- Test: `tests/python/test_brain_workspace.py`
  - Unit tests for discovery, ignore rules, task parsing and log parsing.
- Test: `tests/cases/54-workspace-discovery.sh`
  - Smoke test for isolated folder discovery and CLI output.
- Modify: `spec/guide.md`
  - Add operating docs and commands.

## Task 1: Workspace Templates

**Files:**
- Create: `runtime/templates/workspace/BRAIN.md`
- Create: `runtime/templates/workspace/TASKS.md`
- Create: `runtime/templates/workspace/LOG.md`
- Test: `tests/cases/54-workspace-discovery.sh`

- [ ] **Step 1: Add templates**

Create `runtime/templates/workspace/BRAIN.md`:

```markdown
# Workspace: <name>

## Purpose

Describe what this folder is for in one or two sentences.

## Structure

- `sources/` or `raw/` - source materials; agents must not edit unless explicitly allowed.
- `_work/` - drafts and intermediate work.
- `_final/` - current final documents.
- `_archive/` - old material kept for reference.

## Agent Rules

- Read this file before changing anything in this folder.
- Keep changes inside this folder unless the user explicitly names another path.
- Do not delete, move or rename source materials without explicit approval.
- Record substantial work in `LOG.md` when it exists.
- Use `TASKS.md` when local tasks exist.

## Allowed Roles

- developer
- researcher
- reviewer

## Sensitive Zones

- `sources/`
- `raw/`
- `credentials/`
- `.env`

## Done Checks

- Outputs are saved in the agreed folder.
- Local task acceptance is satisfied.
- Substantial changes are logged.
```

Create `runtime/templates/workspace/TASKS.md`:

```markdown
# Local Tasks

- [ ] [P1] local-001 - Describe the first local task
      role: developer
      acceptance: State the concrete completion check.
```

Create `runtime/templates/workspace/LOG.md`:

```markdown
# Local Log

## 2026-05-27T00:00:00Z | agent-id | note

- Describe the substantial action and files touched.
```

- [ ] **Step 2: Add template smoke assertion**

Append to the new smoke case once it exists:

```bash
test -f "$PROJECT_ROOT/runtime/templates/workspace/BRAIN.md"
test -f "$PROJECT_ROOT/runtime/templates/workspace/TASKS.md"
test -f "$PROJECT_ROOT/runtime/templates/workspace/LOG.md"
grep -q "Agent Rules" "$PROJECT_ROOT/runtime/templates/workspace/BRAIN.md"
grep -q "Local Tasks" "$PROJECT_ROOT/runtime/templates/workspace/TASKS.md"
grep -q "Local Log" "$PROJECT_ROOT/runtime/templates/workspace/LOG.md"
```

- [ ] **Step 3: Run template check**

Run: `bash tests/run.sh workspace`

Expected before the smoke case is complete: no matching case or a failure that names the missing case. Expected after Task 2: PASS.

- [ ] **Step 4: Commit**

```bash
git add runtime/templates/workspace tests/cases/54-workspace-discovery.sh
git commit -m "docs(workspace): add folder-native templates"
```

## Task 2: Discovery and Parsing Helpers

**Files:**
- Create: `runtime/lib/brain_workspace.py`
- Test: `tests/python/test_brain_workspace.py`

- [ ] **Step 1: Write tests for discovery**

Create tests that build a temporary directory with:

```text
root/
  project-a/BRAIN.md
  project-a/TASKS.md
  project-a/LOG.md
  project-b/BRAIN.md
  project-b/.git/ignored/BRAIN.md
  project-b/.venv/ignored/BRAIN.md
```

Assertions:

```python
from pathlib import Path

from brain_workspace import discover_workspaces, find_nearest_workspace


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
    assert found[0].has_tasks is True
    assert found[0].has_log is True


def test_find_nearest_workspace_walks_up(tmp_path):
    workspace = tmp_path / "root" / "project" / "sub"
    workspace.mkdir(parents=True)
    (tmp_path / "root" / "project" / "BRAIN.md").write_text("# Workspace\n", encoding="utf-8")

    assert find_nearest_workspace(workspace) == tmp_path / "root" / "project"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=runtime/lib python3 -m pytest tests/python/test_brain_workspace.py -v`

Expected: FAIL with `No module named 'brain_workspace'`.

- [ ] **Step 3: Implement helpers**

Implement:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "semantic_env",
}


@dataclass(frozen=True)
class WorkspaceInfo:
    path: Path
    brain_file: Path
    title: str
    has_tasks: bool
    has_log: bool
    warnings: tuple[str, ...] = ()


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def _read_title(brain_file: Path) -> str:
    for line in brain_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return brain_file.parent.name


def discover_workspaces(roots: list[Path]) -> list[WorkspaceInfo]:
    found: list[WorkspaceInfo] = []
    for root in roots:
        root = root.expanduser().resolve()
        if not root.exists():
            continue
        for brain_file in sorted(root.rglob("BRAIN.md")):
            if _is_ignored(brain_file.relative_to(root)):
                continue
            folder = brain_file.parent
            found.append(
                WorkspaceInfo(
                    path=folder,
                    brain_file=brain_file,
                    title=_read_title(brain_file),
                    has_tasks=(folder / "TASKS.md").exists(),
                    has_log=(folder / "LOG.md").exists(),
                )
            )
    return found


def find_nearest_workspace(path: Path) -> Path | None:
    current = path.expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "BRAIN.md").exists():
            return candidate
    return None
```

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=runtime/lib python3 -m pytest tests/python/test_brain_workspace.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/lib/brain_workspace.py tests/python/test_brain_workspace.py
git commit -m "feat(workspace): discover folder-native workspaces"
```

## Task 3: CLI Entry Point

**Files:**
- Create: `runtime/bin/brain-workspace`
- Modify: `setup-brain-v2.sh`
- Test: `tests/cases/54-workspace-discovery.sh`

- [ ] **Step 1: Add smoke expectations**

The smoke case should create an isolated root with two workspaces and verify:

```bash
brain-workspace discover --root "$TMP_ROOT" --json
brain-workspace summary --root "$TMP_ROOT"
brain-workspace nearest "$TMP_ROOT/project-a/subdir"
brain-workspace init-template --out "$TMP_ROOT/new-workspace"
```

- [ ] **Step 2: Implement CLI**

Implement Bash wrapper that imports `runtime/lib/brain_workspace.py` through the installed library lookup pattern already used by Brain CLIs. Commands:

```text
brain-workspace discover --root PATH [--json]
brain-workspace summary --root PATH
brain-workspace nearest PATH
brain-workspace init-template --out PATH
```

Expected behavior:

- `discover --json` prints an array of objects with `path`, `title`, `has_tasks`, `has_log`, `warnings`.
- `summary` prints a readable table.
- `nearest` prints the nearest workspace path or exits 1 with a clear message.
- `init-template --out PATH` copies template files into an existing or new folder and refuses to overwrite existing files.

- [ ] **Step 3: Install CLI in setup**

Modify `setup-brain-v2.sh` so `brain-workspace` is installed next to other `runtime/bin` commands.

- [ ] **Step 4: Run focused checks**

Run:

```bash
bash tests/run.sh workspace
python3 -m py_compile runtime/lib/brain_workspace.py
bash -n runtime/bin/brain-workspace
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add runtime/bin/brain-workspace setup-brain-v2.sh tests/cases/54-workspace-discovery.sh
git commit -m "feat(workspace): add workspace discovery CLI"
```

## Task 4: Workspace-scoped Agent Context

**Files:**
- Modify: `runtime/bin/brain-orchestrator`
- Test: `tests/cases/50-orchestrator-console.sh` or new workspace case

- [ ] **Step 1: Add dry-run test**

Add a smoke assertion that:

```bash
brain-orchestrator console --workspace "$TMP_ROOT/project-a" --dry-run
```

Output must include:

```text
workspace: <path>
BRAIN.md: <path>/BRAIN.md
```

- [ ] **Step 2: Implement `--workspace` option**

Add argument parsing for `--workspace PATH`. In dry-run mode, resolve nearest workspace through `brain_workspace.find_nearest_workspace`, include the local `BRAIN.md` path in prompt metadata and keep existing command behavior unchanged when the flag is absent.

- [ ] **Step 3: Run focused checks**

Run:

```bash
bash tests/run.sh workspace
bash tests/run.sh orchestrator-console
```

Expected: both pass.

- [ ] **Step 4: Commit**

```bash
git add runtime/bin/brain-orchestrator tests/cases/50-orchestrator-console.sh tests/cases/54-workspace-discovery.sh
git commit -m "feat(orchestrator): support workspace-scoped dry runs"
```

## Task 5: Pilot Initialization Plan

**Files:**
- Create: `handoff/2026-05-27-phase26-workspace-pilot.md`

- [ ] **Step 1: Create pilot map**

Write a pilot document listing:

```text
/path/to/workspace-alpha
/path/to/workspace-alpha/child
/path/to/workspace-beta
/path/to/workspace-beta/data-export
```

For each folder include:

- purpose
- allowed roles
- sensitive zones
- whether to add `BRAIN.md`
- whether to add `TASKS.md`
- whether to add `LOG.md`
- first safe local task

- [ ] **Step 2: Mark external writes as approval-gated**

The pilot document must state that creating files in those folders requires explicit user approval because they are outside the Brain repo.

- [ ] **Step 3: Commit**

```bash
git add handoff/2026-05-27-phase26-workspace-pilot.md
git commit -m "docs(workspace): plan pilot folder initialization"
```

## Task 6: Docs, Status and Verification

**Files:**
- Modify: `spec/guide.md`
- Modify: `wiki/log.md`

- [ ] **Step 1: Document user workflow**

Add commands and rules:

```text
brain-workspace discover --root /path/to/workspace-alpha
brain-workspace summary --root "/path/to/workspace-beta"
brain-orchestrator console --workspace <folder> --dry-run
```

- [ ] **Step 2: Log roadmap execution**

Append one `wiki/log.md` line for the Phase 26 plan and one line after implementation completes.

- [ ] **Step 3: Run verification**

Run:

```bash
brain-validate
brain-lint
brain-index rebuild
PYTHONPATH=runtime/lib python3 -m pytest tests/python/test_brain_workspace.py -v
bash tests/run.sh workspace
```

If implementation touches `brain-orchestrator`, also run:

```bash
bash tests/run.sh orchestrator-console
```

- [ ] **Step 4: Commit**

```bash
git add spec/guide.md wiki/log.md
git commit -m "docs(workspace): document folder-native workflow"
```

## Self-review

- Spec coverage: contract, templates, discovery, local task/log parsing, scoped launch, pilot plan, docs and verification are covered.
- Placeholder scan: no implementation step relies on vague TODO text; template placeholders are intentional user-editable examples.
- Scope: MVP does not add a central registry, multi-user governance, mass file movement or full portfolio management.
