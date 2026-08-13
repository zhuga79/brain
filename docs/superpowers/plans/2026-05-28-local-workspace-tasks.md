# Local Workspace Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each folder-native workspace usable as a minimal local task queue without creating a central portfolio registry.

**Architecture:** Keep `BRAIN.md`, `TASKS.md` and `LOG.md` as the only workspace state. `runtime/lib/brain_workspace.py` parses and updates local Markdown files; `runtime/bin/brain-workspace` exposes narrow CLI commands for reading and changing local tasks.

**Tech Stack:** Python standard library, shell smoke tests, Markdown files.

---

### Stage 1: Read Local Work

**Files:**
- Modify: `runtime/lib/brain_workspace.py`
- Modify: `runtime/bin/brain-workspace`
- Test: `tests/python/test_brain_workspace.py`
- Test: `tests/cases/54-workspace-discovery.sh`

- [x] Add `next_local_task()` to select the first open local task, optionally filtered by role.
- [x] Add CLI commands `tasks` and `next` with text and JSON output.
- [x] Verify with focused pytest and the workspace smoke case.

### Stage 2: Change Local Task State

**Files:**
- Modify: `runtime/lib/brain_workspace.py`
- Modify: `runtime/bin/brain-workspace`
- Test: `tests/python/test_brain_workspace.py`
- Test: `tests/cases/54-workspace-discovery.sh`

- [x] Add `update_local_task_state()` for safe Markdown marker changes.
- [x] Add `append_local_log()` so state transitions leave local evidence.
- [x] Add CLI commands `take` and `complete`.
- [x] Verify `TASKS.md` markers and `LOG.md` entries in smoke tests.

### Stage 3: Document, Install and Pilot-Check

**Files:**
- Modify: `spec/guide.md`
- Modify: `docs/superpowers/plans/2026-05-28-local-workspace-tasks.md`

- [x] Document local task commands and the no-central-registry boundary.
- [x] Install the updated runtime through `setup-brain-v2.sh`.
- [x] Check read-only commands against the real pilot workspaces.
