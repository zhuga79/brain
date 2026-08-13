# Brain Agent Instructions

This repository configures and ships the local Brain runtime. Any AI agent
working here must treat the current repository root as the live Brain instance
(defaulting to `BRAIN_PATH=.`).

## Required Context

Before making changes, read:

- `./MEMORY.md`
- `./tasks/active.md`
- the role file for your role under `./roles/`

Default role is `developer` unless the task says otherwise.

## Task Protocol

Use Brain tasks as the source of truth.

1. Pick the top open task for your role from `./tasks/active.md`.
2. Generate an agent id in the form `<provider>-<model>-<short-id>`.
3. Acquire a lock before modifying task state:
   `brain-lock acquire <task-id> --as <agent-id>`
4. Mark the task in progress:
   `brain-task take <task-id> --as <agent-id>`
5. Implement the narrowest change that satisfies the task.
6. Verify with the checks named in the task. For code changes, normally run:
   `brain-validate`, `brain-lint`, `brain-index rebuild`, and `bash tests/smoke.sh`.
7. Complete through Brain:
   `brain-task complete <task-id> --as <agent-id>`
8. Release stale or abandoned locks only through `brain-lock`, never by editing
   `.locks` manually.

Do not edit task state by hand unless a Brain CLI command is broken and the
manual repair is itself being documented.

## Curation Rules

- Do not edit files under `./raw/`.
- Human wiki edits have priority over sources.
- Do not overwrite wiki pages with `curation: human` or `protected: true`.
- If source material conflicts with curated wiki content, propose a change
  rather than replacing the curated page.

## Code Rules

- Keep changes scoped to the active ticket.
- Prefer the existing shell/Python style and runtime layout.
- Do not introduce new dependencies unless the ticket explicitly requires it.
- Add focused smoke coverage for regressions.
- Do not run destructive git commands.

## Antigravity / MCP

Brain MCP is available as:

```json
{
  "command": "/home/user/.local/bin/brain-mcp",
  "env": {
    "BRAIN_PATH": "."
  }
}
```

If Antigravity returns HTTP 429 / `RESOURCE_EXHAUSTED`, stop retrying model
requests. Finish local work with Brain CLI checks, record the blocker, and
resume model-driven work after quota recovers or with another CLI.
