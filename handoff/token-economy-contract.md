# Brain Token Economy Contract

Date: 2026-05-06
Status: v1 design contract
Council: `/home/user/brain/council/t-2026-05-06-phase8-token-economy-contract/`
Parent notes: `handoff/2026-05-06-token-optimization-notes.md`

## Decision

Brain will implement a native token-economy layer before integrating external
tools. The default implementation is `brain-compact`: a dependency-light command
that compacts noisy CLI output for Claude, Codex, Gemini, and future CLI agents
while preserving raw artifacts and emitting metrics.

RTK is an optional benchmark/reference, not a runtime dependency and not a
correctness boundary.

## Goals

- Reduce avoidable model-facing output from routine CLI commands.
- Keep raw output recoverable for debugging, evidence, and review.
- Apply one compaction policy across Claude, Codex, Gemini, and future CLIs.
- Expose measurable savings in dashboard and local metrics.
- Preserve manual/human overrides above automatic policy.

## Non-Goals

- No model fine-tuning.
- No dependency on a hosted tokenizer or external service.
- No release gates based on absolute token counts in v1.
- No silent installation of provider hooks.

## `brain-compact` CLI

Required modes:

```bash
brain-compact --kind test -- bash tests/smoke.sh
brain-compact --kind search -- rg -n "pattern" runtime
brain-compact --kind read < runtime/mcp/server.py
brain-compact --kind git -- git diff -- runtime/bin/brain-dashboard
```

Required flags:

| Flag | Meaning |
|---|---|
| `--kind <class>` | command class, see list below |
| `--json` | emit machine-readable metrics/result envelope |
| `--raw` | bypass compaction for this invocation |
| `--strict` | fail closed on parser uncertainty |
| `--role <role>` | role policy input |
| `--provider <provider>` | provider policy/metrics input |
| `--task <id>` | task id for metrics/artifact namespace |
| `--session <id>` | agent/session id for metrics/artifact namespace |

`brain-compact` must be deterministic: same input, same flags, same policy
version, same output.

## Command Classes

V1 command classes:

- `read`
- `list`
- `search`
- `git`
- `test`
- `build`
- `lint`
- `logs`
- `package-manager`
- `web-extract`
- `unknown`

Each class must document a decision-surface invariant: exact fields/lines that
must survive compaction byte-for-byte.

Examples:

| Class | Must Preserve |
|---|---|
| `test` | failing assertion text, file path, line number, failing test name, first/last relevant stack frame |
| `git` | file paths, hunk headers, changed lines requested by the user, conflict markers |
| `search` | matching file path, line number, matched text, first/last match per file |
| `read` | requested line ranges, headings, signatures, source references |
| `logs` | timestamps, severity, error code, first/last occurrence, correlation ids |
| `web-extract` | source URL, title, quoted/cited passages, retrieval timestamp |

## Raw Artifacts

Raw artifact preservation is default-on for every compacted run.

Required behavior:

- write raw stdout/stderr to `.brain/artifacts/<session-or-lock>/<id>.log`;
- use directory permissions `0700`;
- keep artifacts gitignored;
- include artifact path in compacted output;
- provide explicit `--raw` and future `--no-artifact` escape hatches;
- document stdout/stderr interleaving behavior;
- redact secrets/PII according to a documented redaction policy before any
  artifact leaves the local machine.

Compacted output is never the only truth.

## Parser Confidence

`brain-compact` must not silently emit best-effort compact output when it cannot
confidently parse a class.

Modes:

- default: raw pass-through with warning marker on uncertainty;
- `--strict`: non-zero exit on uncertainty;
- `--raw`: bypass compaction and still record metrics as raw mode.

Binary output must pass through raw mode with a warning and artifact path.

## Elision

Deduplication must use explicit markers.

Required rule:

- preserve first and last occurrence;
- replace middle repetitions with:
  `[..., N similar lines elided ...]`

Silent collapse is forbidden.

## Policy Precedence

Compaction policy resolves in this order, highest first:

1. per-invocation flag;
2. task-level override;
3. role default;
4. path rule;
5. global default.

Manual human instruction overrides all generated policy.

Role defaults:

| Role | Default |
|---|---|
| `developer` | compact test/build/search output; preserve exact failing lines |
| `reviewer` | compact broad scans; preserve diffs, security findings, and evidence |
| `architect` | summarize file maps and decisions; avoid full source dumps |
| `researcher` | compact surrounding text; preserve citations, URLs, source refs, and quoted passages |
| `lawyer` | preserve source/legal text and citations verbatim |
| `tax-advisor` | preserve source/tax text and citations verbatim |
| `linter` | compact index/lint output; show only errors, broken links, and summaries |

## Metrics Schema

Append-only metrics path:

`.brain/metrics/compact.jsonl`

Each line is JSON:

```json
{
  "ts": "2026-05-06T10:42:00Z",
  "command_class": "test",
  "role": "developer",
  "provider": "gemini",
  "session": "gemini-3-flash-phase8",
  "task": "t-2026-05-06-phase8-brain-compact-cli",
  "raw_bytes": 120000,
  "compact_bytes": 18000,
  "raw_tokens_est": 30000,
  "compact_tokens_est": 4500,
  "savings_pct": 85.0,
  "artifact_path": ".brain/artifacts/gemini-3-flash-phase8/cmd-001.log",
  "parser_confidence": "high",
  "mode": "normal",
  "policy_version": 1
}
```

Token fields are estimates and must use `_est`. Release gates may use fixture
regressions and artifact recoverability, not absolute token counts.

## Provider Adapters

All adapters are opt-in, inspectable, dry-run capable, and reversible.

| Provider | Adapter |
|---|---|
| Claude Code | `PreToolUse(Bash)` hook that rewrites command vectors through `brain-compact` |
| Codex | project command guidance and compact command aliases |
| Gemini CLI | launch profile/wrapper that sets role/provider/task/session fields |

Hook safety rules:

- rewrite argv/vector form, not reconstructed shell strings;
- rewriter is pure and side-effect-free;
- generated hook config includes content hash;
- install/uninstall is logged in `wiki/log.md`;
- no silent install.

## Tests

Required fixture layout:

```text
tests/compact/fixtures/<class>/
├── case-001.raw
└── case-001.expected
```

Adding a new command class requires fixtures that prove decision-surface
invariants. Smoke/focused tests must fail on decision-surface regressions.

Minimum v1 fixtures:

- failing pytest/bash test output;
- repeated stack trace/log output;
- `rg -n` multiple matches;
- `git diff` with multiple hunks;
- lint output with repeated warnings;
- binary/unknown output fallback.

## RTK

RTK is useful as a reference implementation and benchmark comparator. Brain will
not depend on RTK for core behavior in v1.

Benchmark rule:

- collect representative Brain session corpus first;
- compare Brain-native compaction and RTK on the same corpus;
- publish methodology and results in `wiki/token-economy.md`;
- consider optional RTK integration only if it materially outperforms Brain-native
  compaction on representative workloads.

## Acceptance

- Contract exists and is linked from handoff.
- `brain-compact` implementation follows this contract.
- Raw artifacts are created by default for compacted output.
- Metrics are append-only and dashboard-readable.
- Provider adapters are opt-in and reversible.
- `brain-validate`, `brain-lint`, and relevant smoke/focused tests pass.
