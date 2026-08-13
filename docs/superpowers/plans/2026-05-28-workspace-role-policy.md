# Workspace Role Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight local protocol that decides which agent roles may work inside each folder-native workspace.

**Architecture:** Keep authority local to each folder through `BRAIN.md`; do not create a central document registry. Add a workspace profile, role policy and action gates to templates and parsers, then enforce the policy in workspace task selection and workspace-aware `brain-run` prompts.

**Tech Stack:** Markdown workspace files, Python helpers in `runtime/lib`, Bash/Python CLIs in `runtime/bin`, shell smoke tests.

---

## Stages and Owners

### Stage 1: Contract

**Owner:** `architect`

- [x] Define the `Workspace Profile`, `Role Policy` and `Action Gates` Markdown contract.
- [x] Decide how unknown roles are handled: blocked by default unless explicitly listed in `core`, `available` or `gated`.
- [x] Record the contract in docs and ensure it stays local to `BRAIN.md`.

### Stage 2: Runtime

**Owner:** `developer`

- [x] Add parser support for profile, role policy and action gates.
- [x] Update workspace templates with the new protocol.
- [x] Add `brain-run --workspace PATH` so local `TASKS.md` tasks appear in agent prompts.
- [x] Make `brain-workspace next/take` reject roles that are not allowed by the workspace policy.
- [x] Add focused smoke coverage in `tests/cases/54-workspace-discovery.sh`.

### Stage 3: Review

**Owner:** `reviewer`

- [x] Review the contract and runtime behavior for accidental central-registry drift.
- [x] Check that legal, finance and send-mail actions remain gated by explicit user approval.
- [x] Verify tests cover the role-policy happy path and blocked-role path.

### Stage 4: Pilot

**Owner:** `pm`

- [x] Apply the protocol to `/path/to/workspace-beta`.
- [x] Apply the protocol to `/path/to/workspace-alpha` or its active child workspace.
- [x] Confirm that `lawyer` can take the Zhukov pretension-review task and that unsafe actions remain gated.
