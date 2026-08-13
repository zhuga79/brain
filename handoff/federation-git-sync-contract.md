# Federation / Git-Sync Contract

Date: 2026-05-06
Phase: 9
Decision source: `council/t-2026-05-06-federation-git-sync-design-con/`
Status: design accepted, implementation not approved

## Purpose

Federation lets multiple Brain vaults exchange durable knowledge and task
history through git while preserving local runtime safety. Phase 9 defines the
contract only. It does not implement automatic pull, push, merge or conflict
resolution.

## Non-Goals

- No automatic sync writes.
- No distributed lock protocol.
- No conflict-free replicated task queue.
- No hosted Brain service.
- No auto-pull from untrusted remotes.
- No committing secrets, provider cache, CLI mappings or raw handoff excerpts.

## Source Categories

### Durable, Reviewable

These files can be reviewed and synced by git:

- `MEMORY.md`
- `roles/`
- `teams/`
- `doctrine/`
- `prd/`
- `raw/`
- `wiki/`
- `tasks/active.md`
- `tasks/done.md`
- `tasks/SCHEMA.md`
- `council/`
- `learning/incidents/`
- `learning/lessons/`

### Generated Or Runtime-Local

These must stay local and ignored:

- `.locks/`
- `.brain/index/`
- `.brain/vector/`
- `.brain/token-metrics.jsonl`
- `.provider-health.json`
- `.cli-mapping.sh`
- `handoff/ORCHESTRATOR_HANDOFF.md`
- `wiki/_views/`
- local CLI/auth config outside the vault

## Merge Rules

### `raw/`

`raw/` is immutable evidence. New files may be added. Existing source files must
not be rewritten by sync automation. If a source needs correction, add a new raw
artifact and link it from a wiki update proposal.

### `wiki/`

Merge by page. Human curation wins:

- `curation: human` has priority over imported/source-derived text.
- `protected: true` must not be overwritten automatically.
- `source_policy: ignored` means raw sources do not apply to that page.
- Broken wikilinks after merge block release until fixed.

### `tasks/active.md`

This is the highest-risk file. Merge by task id, not by line position.

Rules:

- Same task id with different title/role/mode/acceptance is a conflict.
- State precedence is review-based, not automatic.
- `[x]` in one branch and `[ ]` or `[~]` in another requires checking
  `tasks/done.md` and `wiki/log.md`.
- `[~]` in remote input must not import a remote lock. Treat it as a conflict
  or downgrade to `[ ]` only after review.
- New task ids can be appended into the correct priority section.

### `tasks/done.md`

Merge by task id and keep one done record per task. Prefer the record with the
most complete machine fields (`completed`, `by`, `summary`). Do not delete
history without human review.

### `council/`

Merge by task directory and role file. If opinions change after synthesis, the
synthesis is stale and must be regenerated or marked blocked. Never synthesize
over missing required roles.

### `learning/`

Merge by incident/lesson id. Status folder conflicts (`pending` vs `active`,
`active` vs `deprecated`) require review. Active lessons remain bounded by the
injection policy; federation must not increase injected context automatically.

### `wiki/log.md`

Append-only interleaving is acceptable. If duplicate operation lines appear,
dedupe only when timestamp, operation, task id and agent are identical.

## Lock Ownership

Locks are local runtime state. `.locks/` must never be synced. A remote agent's
`[~]` marker does not grant local lock ownership. Before local work, the agent
must acquire a new local lock through `brain-lock` or `brain-task take`.

## Conflict Workflow

Before merging a remote Brain branch:

```bash
git fetch <remote>
git checkout -b review/federation-<date> <remote>/<branch>
brain-index rebuild --with-obsidian
brain-status
brain-validate
brain-lint --sync-report
bash tests/smoke.sh
git diff --check
```

Then review:

- task id duplicates and state conflicts;
- protected/human-curated wiki edits;
- raw file rewrites;
- learning status moves;
- council synthesis freshness;
- accidental generated/runtime files.

Only after review should changes be merged into the main local Brain branch.

## Future Implementation Gates

Any automatic federation tool needs separate tickets for:

- task queue parser/merger with explicit conflict output;
- protected wiki merge guard;
- generated/runtime file preflight;
- security review for secrets and remote trust;
- dry-run mode with no writes;
- rollback plan.
