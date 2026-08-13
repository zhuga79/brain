# `brain-federation` CLI Contract

Date: 2026-05-06
Phase: 10
Decision source: `council/t-2026-05-06-brain-federation-contract/`
Status: accepted for implementation

## Purpose

`brain-federation` is a read-only dry-run CLI for reviewing proposed Brain vault
sync changes before a human merge. Phase 10 does not implement automatic pull,
push, merge or conflict resolution.

## Commands

```bash
brain-federation support [--json]
brain-federation preflight [--repo <path>] [--brain <path>] [--json]
brain-federation tasks-check --active <path> [--done <path>] [--json]
brain-federation plan --repo <path> [--brain <path>] [--json] [--out <plan.json>]
brain-federation import-tasks --plan <plan.json> --as <agent-id> [--yes] [--json]
brain-federation write-wiki-proposals --plan <plan.json> --as <agent-id> [--yes] [--json]
```

Phase 10 commands are read-only. Phase 11 write commands consume a plan and
perform exactly one bounded local write class.

## Exit Codes

- `0`: no `block` findings.
- `1`: one or more `block` findings.
- `2`: usage error, missing required input or unreadable path.

`review`, `warn` and `info` findings do not by themselves make the command fail.

## JSON Schema

All JSON output uses schema version 1:

```json
{
  "ok": false,
  "schema_version": 1,
  "mode": "preflight",
  "repo": "/path/to/repo",
  "brain": "/path/to/brain",
  "summary": {
    "block": 1,
    "review": 1,
    "warn": 0,
    "info": 0
  },
  "findings": [
    {
      "code": "runtime-file-included",
      "severity": "block",
      "path": ".provider-health.json",
      "message": "runtime-local provider health cache must not be synced",
      "hint": "remove from commit and keep it in .gitignore"
    }
  ]
}
```

Allowed severities:

- `block`
- `review`
- `warn`
- `info`

## Required Finding Codes

### Blocking

- `runtime-file-included`: `.locks/`, `.brain/`, `.provider-health.json`,
  `.cli-mapping.sh`, `handoff/ORCHESTRATOR_HANDOFF.md`, `wiki/_views/`.
- `raw-rewrite`: existing `raw/` file modified or deleted.
- `protected-wiki-edit`: changed wiki page with `protected: true`.
- `human-curated-wiki-edit`: changed wiki page with `curation: human`.
- `task-duplicate-id`: duplicate task id in a task file.
- `task-field-conflict`: same task id has changed title, role, mode or
  acceptance across compared inputs.
- `task-imported-in-progress`: remote/proposed task state is `[~]`.
- `task-done-open-conflict`: same task id is done in one input and open or
  in-progress in another.
- `done-duplicate-id`: duplicate done record for one task id.

### Review Required

- `provider-matrix-change`: `wiki/provider-matrix.json` changed.
- `provider-command-change`: provider command changed inside matrix.
- `learning-status-conflict`: lesson id appears in multiple status folders.
- `council-synthesis-stale`: role opinion changed after synthesis.

### Warning

- `possible-secret`: simple token/password/API-key pattern in diff or handoff.
- `missing-generated-ignore`: `.gitignore` does not cover generated runtime
  paths.
- `outside-git-repo`: preflight ran without git metadata and used path checks
  only.

## Read-Only Guarantees

The command must not:

- write files;
- run provider CLIs;
- contact remotes;
- create commits/tags;
- acquire Brain locks;
- modify task state.

These guarantees apply to `support`, `preflight`, `tasks-check` and `plan`
except that `plan --out <file>` writes exactly the requested JSON file.

## Phase 11 Plan/Write Contract

`plan` output keeps the Phase 10 JSON envelope and adds:

- `kind: "federation-plan"`
- `generated_at`
- `plan_id: "sha256:<hex>"`
- `generator: {tool, version}`
- `source_state.repo_head`
- `source_state.repo_status`
- `source_state.repo_status_sha256`
- `source_state.brain_active_sha256`
- `source_state.brain_done_sha256`
- `task_imports[]`, `skipped_tasks[]`
- `wiki_proposals[]`, `skipped_wiki[]`
- `required_confirmations[]`
- `read_only: true`
- `write_policy{}`

`import-tasks`:

- dry-run by default;
- requires `--yes` to write;
- refuses plan `block` findings, stale source state, duplicate task ids,
  non-open task state and active/done conflicts;
- writes only `tasks/active.md` plus audit lines in `wiki/log.md`;
- uses shared `.locks/tasks-active`, tempfile next to `tasks/active.md` and
  atomic replace.

`write-wiki-proposals`:

- dry-run by default;
- requires `--yes` to write proposal artifacts;
- writes only `$BRAIN_PATH/proposals/federation/<timestamp>/`;
- creates `manifest.json`, proposed markdown, unified diff and target meta JSON;
- never writes to `wiki/` or `raw/`;
- treats protected/human-curated wiki blocks as expected for proposal creation
  only; all other block findings still refuse.

Optional secret scanner:

- configured only through `BRAIN_SECRET_SCANNER_CMD`;
- receives repo path as the final argument;
- emits JSON-lines findings;
- missing/failing scanner is warning/fallback only and never triggers installs.

## Test Requirements

Focused tests must prove:

- runtime/generated files produce `block`;
- raw rewrites produce `block`;
- protected/human-curated wiki edits produce `block`;
- provider matrix command changes produce `review`;
- duplicate task ids and imported `[~]` produce `block`;
- clean fixtures exit `0`;
- `--json` is stable and parseable.
