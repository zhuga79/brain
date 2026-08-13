# Provider Health Refresh Contract

Date: 2026-05-06
Phase: 9
Decision source: `council/t-2026-05-06-provider-health-refresh-contra/`
Status: accepted for implementation

## Purpose

Brain routes work through a manually curated provider/model matrix and a local
cached health file. Provider health refresh updates that cache only when the
operator explicitly asks for it. Dashboard, `brain-status`, MCP tools and SSE
polling remain read-only consumers and must not spend provider quota.

## Source Of Truth

Routing priority remains:

1. explicit task or role override;
2. `$BRAIN/wiki/provider-matrix.json`;
3. `$BRAIN/.cli-mapping.sh` launch command;
4. runtime default matrix.

`$BRAIN/.provider-health.json` is generated local state. It can downgrade or
annotate candidates for the current machine/account, but it does not replace
the human-curated matrix.

## CLI Shape

Required commands:

```bash
brain-provider status [--json] [--role <role>] [--provider <name>] [--model <id>]
brain-provider refresh --provider <name> --model <id> [--timeout <seconds>] [--yes] [--json]
brain-provider mark --provider <name> --model <id> --status <status> --reason <text> --yes [--json]
brain-provider clear --provider <name> --model <id> --yes [--json]
```

Rules:

- `status` is read-only.
- `refresh` is dry-run by default and must show the target and planned probe.
- `refresh --yes` may run one live probe and write one cache item.
- `mark` and `clear` mutate the cache and therefore require `--yes`.
- One provider/model target per command in Phase 9.
- No matrix-wide refresh, dashboard refresh button, status-path refresh, MCP
  read-path refresh or SSE-triggered refresh in Phase 9.

## Cache Schema

File: `$BRAIN/.provider-health.json`

```json
{
  "version": 1,
  "updated": "2026-05-06T14:19:00Z",
  "items": {
    "gemini/gemini-3-flash-preview": {
      "provider": "gemini",
      "model": "gemini-3-flash-preview",
      "status": "rate-limited",
      "source": "probe",
      "reason": "HTTP 429 RESOURCE_EXHAUSTED",
      "checked_at": "2026-05-06T14:19:00Z",
      "ttl_seconds": 3600
    }
  }
}
```

Allowed `status` values:

- `configured`
- `available`
- `unavailable`
- `rate-limited`
- `quota-exhausted`
- `model-not-found`
- `auth-required`
- `error`

Allowed `source` values:

- `probe`
- `manual`
- `import`

Writers must preserve unrelated cache items and fail without deleting invalid
existing cache content.

## Probe Safety

Live probes must be bounded:

- require `--yes`;
- require a single provider/model;
- use a timeout, default 30 seconds or less;
- use the cheapest available CLI check;
- store only sanitized summaries, never full prompts, tokens, env vars or raw
  provider output;
- preserve provider-specific trace IDs only when they are explicitly supplied or
  known safe.

## Read-Only Consumers

These surfaces may read cached health through `collect_provider_status()`:

- `brain-status`
- dashboard `/api/providers`
- dashboard render and SSE updates
- MCP read tools
- `brain-handoff`
- `brain-launch --dry-run`

They must not invoke provider CLIs or mutate `.provider-health.json`.

## Tests

Focused implementation tests must cover:

- `brain-provider status --json` returns the same read model as existing cached
  provider status.
- `brain-provider refresh ...` without `--yes` has no side effects.
- `brain-provider refresh ... --yes` writes only the targeted item.
- `brain-provider mark ... --yes` records `source: manual`.
- `brain-provider clear ... --yes` removes only the targeted item.
- invalid existing cache is not silently discarded.
- dashboard/status read paths do not execute live probes.

## Non-Goals

- No automatic matrix-wide probing.
- No hosted provider health service.
- No secrets in cache, logs, dashboard or handoff artifacts.
- No replacement of manual provider priority decisions.
