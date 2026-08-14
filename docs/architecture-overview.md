---
title: Architecture Overview
type: concept
created: 2026-05-16
updated: 2026-08-14
curation: agent
protected: false
source_policy: advisory
tags: [architecture, core, split-root]
sources: []
related: [decision-public-source-of-truth, decision-post-inversion-cycle, decision-runtime-core-boundaries, decision-role-model-routing]
visibility: public
---

# Architecture Overview

Brain is a local, file-backed runtime for one operator with multiple LLM
agents. In the current architecture the system and the data live in different
roots.

## Runtime layout

| Layer | Ownership | Contents |
|---|---|---|
| System checkout | public repo | `runtime/`, `tests/`, `roles/`, `teams/`, `doctrine/`, `skills/`, `spec/`, `docs/`, `config/` |
| Data root | private repo / `~/brain` | `wiki/`, `tasks/`, `raw/`, `council/`, `handoff/`, `prd/`, `.locks/`, `.brain/` |
| Installed tools | local machine | `~/.local/bin/brain-*`, `~/.local/share/brain/`, `~/.local/share/brain-mcp/` |

`BRAIN_PATH` points to the data root. `BRAIN_SYSTEM_PATH` points to the system
checkout. Without `BRAIN_SYSTEM_PATH`, Brain falls back to the legacy
single-root lookup.

## Core contracts

### Queue and transactions

- Root queue state lives in `tasks/active.md` and `tasks/done.md`.
- `runtime/lib/brain_core/taskfile.py` owns writes to that queue.
- Completion is crash-recoverable through a completion journal plus atomic
  replace.
- `runtime/lib/brain_core/prdfile.py` is the PRD adapter for the same queue
  and runs under the same queue lock.
- Workspace-local tasks are separate: `brain_workspace.py` owns
  `TASKS.md` + `LOG.md` transactions inside a workspace folder.

### Routing

- Role-to-command resolution lives in `runtime/lib/brain_provider.py`.
- Candidates come from `config/routing.json`.
- Missing local executables are skipped with warnings.
- Explicit `virtual` / `remote` candidates remain eligible.
- If every candidate is unavailable, Brain falls back to `defaults.cli`
  instead of aborting role resolution.

### System/data boundary

- System assets must be changed in the system checkout, then reinstalled.
- Data root must not shadow live system directories such as `runtime/`,
  `roles/`, `teams/`, `doctrine/`, `skills/`, `spec/`, `docs/`, `tests/`,
  `config/`.
- `setup-brain-v2.sh`, `brain-validate`, and the write-path pre-commit guard
  enforce that boundary in split-root mode.

## Operator flows

### Install or update the live system

1. Change the public system checkout.
2. Reinstall from that checkout with `./setup-brain-v2.sh` or `brain-ops update`.
3. Run the release gates before treating the install as live.

Installed CLI launchers are copied into `~/.local/bin`, so editing
`runtime/bin/*` does not update the live instance until reinstall.

### MCP

`install-brain-mcp.sh` installs a canonical MCP runtime tree into
`~/.local/share/brain-mcp/` and a launcher into `~/.local/bin/brain-mcp`.
MCP queue tools are expected to match shell queue semantics because both go
through the same queue domain layer.

## Release gates

System health is intentionally multi-signal:

- CI runs smoke plus pytest for the public repo.
- Local pre-commit runs smoke plus pytest before system commits.
- Runtime health checks for the live instance still include `brain-validate`
  and `brain-lint`.

No single badge or status line is the whole contract.
