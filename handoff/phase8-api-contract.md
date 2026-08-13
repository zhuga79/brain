# Phase 8 Visual Shell API Contract

Date: 2026-05-06
Status: v1 contract
Parent PRD: `handoff/2026-05-06-phase8-prd.md`
Owner role: `architect`

## Decision

The Phase 8 visual shell must use Brain's existing file and CLI contracts as the
source of truth. The UI may add aggregator endpoints, but it must not invent a
separate task, lock, council, release, learning, provider, or token state model.

The initial API surface is:

- existing dashboard endpoints for read models;
- existing `POST /api/tasks/<id>` for task write actions;
- existing CLI `--json` commands for release and task contracts;
- new Phase 8 endpoints only where no stable contract exists yet.

## Contract Rules

- All timestamps are UTC ISO-8601 strings ending in `Z`.
- Task IDs and role names are opaque strings from `tasks/active.md`.
- UI write actions must call existing Brain commands instead of editing files.
- Human-curated/protected wiki pages remain higher priority than generated data.
- Raw command output and source evidence must remain recoverable when compacted.
- Unknown fields must be ignored by clients; removed fields require a contract
  note in this file.

## Current Endpoints

These endpoints already exist in `brain-dashboard serve` and are safe to build
against in Phase 8.

| Endpoint | Method | Source | Purpose |
|---|---:|---|---|
| `/events` | GET | `collect_status()` | SSE live counters every 5 seconds |
| `/api/status` | GET | `collect_status()` | full dashboard read model |
| `/api/index` | GET | `read_index()` | index health and rebuild hint |
| `/api/tasks` | GET | `collect_status().tasks.active` | active task list and summary |
| `/api/audit` | GET | `wiki/log.md` | recent write-action audit entries |
| `/api/learning` | GET | `collect_learning_stats()` | learning counts and recent incidents |
| `/api/metrics` | GET | `collect_metrics()` | flat orchestration/learning/webhook/policy counters |
| `/api/tasks/<id>?as=<agent>&action=<action>` | POST | `brain-task` subprocess | task write actions |

Existing write actions: `take`, `release`, `complete`.

## `/api/status`

`/api/status` is the canonical Phase 8 page-load contract. The visual shell
should render task board, lock badges, council summary, index health, and
learning counters from this response before adding narrower endpoints.

```json
{
  "brain": "/home/user/brain",
  "tasks": {
    "summary": {
      "active_count": 15,
      "done_count": 71,
      "states": {" ": 14, "~": 1},
      "priorities": {"P1": 9, "P2": 6},
      "roles": {"architect": 3, "developer": 8, "linter": 2, "reviewer": 2},
      "modes": {"solo": 13, "council": 2}
    },
    "active": [
      {
        "id": "t-2026-05-06-phase8-status-api-contract",
        "state": "~",
        "priority": "P1",
        "role": "architect",
        "mode": "solo",
        "title": "Закрепить JSON-контракт visual shell"
      }
    ],
    "done": [
      {
        "id": "t-2026-05-06-phase8-handoff-sync",
        "state": "x",
        "priority": "P0",
        "role": "linter",
        "mode": "solo",
        "title": "Синхронизировать handoff после Stage 7 debt closure"
      }
    ]
  },
  "locks": {
    "count": 1,
    "stale_count": 0,
    "items": [
      {
        "task_id": "t-2026-05-06-phase8-status-api-contract",
        "owner": "codex-5.5-xhigh-phase8",
        "age_seconds": 42,
        "ttl_seconds": 600,
        "stale": false
      }
    ]
  },
  "council": {
    "count": 4,
    "items": [
      {
        "task_id": "t-2026-05-01-pick-llm-stack",
        "files": ["architect.md", "researcher.md", "reviewer.md", "synthesis.md"],
        "file_count": 4
      }
    ]
  },
  "index": {
    "status": "present",
    "health": "ok",
    "next_step": "",
    "generated_at": "2026-05-06T10:15:55Z",
    "page_count": 9,
    "raw_count": 1,
    "link_count": 18,
    "search_docs": 13,
    "stale_files": []
  },
  "learning": {
    "available": true,
    "counts": {
      "incidents": 0,
      "pending": 0,
      "approved": 0,
      "active": 0,
      "deprecated": 0
    },
    "recent_incidents": []
  }
}
```

## `/events`

SSE event payloads are lightweight deltas for live counters. They are not a full
replacement for `/api/status`.

```json
{
  "ts": "2026-05-06T10:30:00Z",
  "tasks": {
    "active_count": 15,
    "done_count": 71,
    "states": {" ": 14, "~": 1},
    "priorities": {"P1": 9, "P2": 6},
    "roles": {"architect": 3, "developer": 8},
    "modes": {"solo": 13, "council": 2}
  },
  "locks": {"count": 1, "stale_count": 0},
  "council": {"count": 4},
  "index": {"health": "ok"}
}
```

## `/api/tasks`

`/api/tasks` is the narrow active-task endpoint used by task-board UI.

```json
{
  "tasks": [
    {
      "id": "t-2026-05-06-phase8-dark-shell-foundation",
      "state": " ",
      "priority": "P1",
      "role": "developer",
      "mode": "solo",
      "title": "Базовая dark visual shell"
    }
  ],
  "summary": {
    "active_count": 15,
    "done_count": 71,
    "states": {" ": 14, "~": 1},
    "priorities": {"P1": 9, "P2": 6},
    "roles": {"developer": 8},
    "modes": {"solo": 13, "council": 2}
  }
}
```

## Task Write Action

The visual shell must call the existing POST endpoint; the server delegates to
`brain-task` and preserves lock semantics.

Request:

```http
POST /api/tasks/t-2026-05-06-phase8-dark-shell-foundation?as=gemini-3-flash-phase8&action=take
```

Response:

```json
{
  "ok": true,
  "task_id": "t-2026-05-06-phase8-dark-shell-foundation",
  "action": "take",
  "agent": "gemini-3-flash-phase8",
  "output": "took: t-2026-05-06-phase8-dark-shell-foundation",
  "error": ""
}
```

Error response:

```json
{
  "ok": false,
  "task_id": "t-2026-05-06-phase8-dark-shell-foundation",
  "action": "take",
  "agent": "gemini-3-flash-phase8",
  "output": "",
  "error": "locked by: codex-5.5-xhigh-phase8"
}
```

## `/api/metrics`

Current metrics are flat counters. Phase 8 UI should show these now and append
token/provider metrics later without changing existing keys.

```json
{
  "generated_at": "2026-05-06T10:30:00Z",
  "orchestration": {
    "tasks_active": 15,
    "tasks_done": 71,
    "locks_active": 1,
    "locks_stale": 0,
    "council_count": 4
  },
  "learning": {
    "available": true,
    "incidents": 0,
    "pending": 0,
    "approved": 0,
    "active": 0,
    "deprecated": 0
  },
  "webhook": {
    "dead_letter_count": 0
  },
  "policy": {
    "status": "ok",
    "gates_passed": 5,
    "gates_failed": 0
  }
}
```

## Phase 8 Additions

The following read models are required for Phase 8 but are not fully present in
the current dashboard contract.

### Council Workspace

Add `/api/council` after `brain-council check <id>` output is available in a
stable parseable shape.

```json
{
  "items": [
    {
      "task_id": "t-2026-05-06-phase8-provider-matrix",
      "roles_required": ["architect", "reviewer", "researcher"],
      "opinions": [
        {
          "role": "architect",
          "status": "valid",
          "agent": "codex-5.5-xhigh-phase8",
          "written": "2026-05-06T10:30:00Z",
          "path": "council/t-2026-05-06-phase8-provider-matrix/architect.md"
        },
        {
          "role": "reviewer",
          "status": "missing",
          "agent": "",
          "written": "",
          "path": "council/t-2026-05-06-phase8-provider-matrix/reviewer.md"
        }
      ],
      "synthesis": {
        "status": "not_ready",
        "path": "council/t-2026-05-06-phase8-provider-matrix/synthesis.md"
      }
    }
  ]
}
```

Allowed opinion statuses: `missing`, `invalid`, `valid`.
Allowed synthesis statuses: `not_ready`, `ready`, `done`.

### Release Gates

Expose `brain-release check --json` either as `/api/release` or under
`/api/metrics.release`. The shape should preserve the existing CLI JSON:

```json
{
  "ok": false,
  "brain_path": "/home/user/brain",
  "repo": "/home/user/Документы/Brain/files",
  "passed": [{"gate": "brain-lint", "detail": ""}],
  "failed": [{"gate": "active=0", "detail": "active=15 tasks remain"}],
  "total": 5,
  "passed_count": 1,
  "failed_count": 1
}
```

### Provider Health

Add a machine-readable provider surface only after the provider matrix ticket
lands. It must be local and cheap by default; live quota probes should be opt-in.

```json
{
  "generated_at": "2026-05-06T10:30:00Z",
  "providers": [
    {
      "provider": "codex",
      "model": "gpt-5.5",
      "status": "configured",
      "roles": ["architect", "reviewer"],
      "priority": 1,
      "last_probe": "",
      "last_error": ""
    },
    {
      "provider": "gemini",
      "model": "gemini-3-flash",
      "status": "configured",
      "roles": ["developer"],
      "priority": 1,
      "last_probe": "",
      "last_error": ""
    }
  ],
  "manual_override": true
}
```

Allowed statuses: `configured`, `unconfigured`, `available`, `rate_limited`,
`unavailable`, `unknown`.

### Token Economy

Add token economy metrics after `brain-compact` lands. Raw artifacts are
mandatory whenever model-facing output is truncated.

```json
{
  "generated_at": "2026-05-06T10:30:00Z",
  "session": {
    "raw_bytes": 240000,
    "compact_bytes": 42000,
    "estimated_raw_tokens": 60000,
    "estimated_compact_tokens": 10500,
    "estimated_saved_tokens": 49500,
    "savings_percent": 82.5
  },
  "by_command_class": [
    {
      "class": "rg",
      "count": 12,
      "estimated_saved_tokens": 12000,
      "raw_artifacts": [".brain/artifacts/compact/rg-20260506-103000.log"]
    }
  ]
}
```

## Implementation Mapping

| Contract area | Current source | Phase 8 implementation note |
|---|---|---|
| status page load | `/api/status`, `collect_status()` | use as first UI render model |
| live counters | `/events` | update counters only; refetch full status for details |
| active tasks | `/api/tasks`, `brain-task list --json` | use dashboard endpoint in browser, CLI JSON in tests |
| task details | `brain-task show <id> --json` | add endpoint only if UI needs direct task drawer fetch |
| task writes | `POST /api/tasks/<id>` | no direct file edits |
| locks | `/api/status.locks`, `brain-lock status` | add full `brain-lock list --json` only if needed |
| council | `/api/status.council` | add `/api/council` with opinion validation in later ticket |
| release | `brain-release check --json` | add `/api/release` wrapper in visual shell ticket |
| learning | `/api/learning` | extend with review actions in learning UI ticket |
| provider health | `.cli-mapping.sh`, future provider matrix | add after provider matrix decision |
| token economy | future `brain-compact` metrics | add after token economy contract and CLI |

## Risks

- Duplicating task parsing in the UI would create split-brain state; use
  `brain_tasks.py` and existing CLI JSON instead.
- A single huge `/api/v1/status` endpoint can become slow; Phase 8 should start
  from current endpoints and add narrower endpoints when needed.
- Live provider probes can burn quota; default provider health must read config
  and cached last errors, not call every provider on each page load.
- Token compaction must never discard raw evidence without an artifact path.
