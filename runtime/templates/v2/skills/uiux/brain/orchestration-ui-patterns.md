---
name: orchestration-ui-patterns
version: 0.1.0
last_updated: 2026-05-07
status: active
owner_role: designer
group: brain
applies_to: [designer, developer, reviewer]
invoked_by: [designer, developer, reviewer, product]
consumed_by: [designer, developer, reviewer]
trigger: Use when designing UI for agents, locks, councils, provider health, release gates, or task lifecycle.
requires: [workflow-design]
forbidden_zones: [lock-bypass, hidden-agent-ownership, direct-wiki-overwrite]
output_format: structured-md
max_lines: 200
---

## Trigger

Run this whenever the UI must show Brain orchestration state or let an operator
act on tasks, locks, councils, providers, or release gates.

## Inputs

- Task lifecycle and lock protocol.
- Council state or provider health data.
- Release gate or policy result.

## Checklist

- Show ownership: agent id, role, lock age, and stale state.
- Make lifecycle state transitions explicit.
- Separate read-only status from write actions.
- Put release blockers above informational details.
- Define the UI state matrix:
  - empty: no active tasks/councils/locks.
  - loading: SSE/API refresh in progress.
  - error: stale index, stale lock, auth, policy, or provider error.
  - success: current healthy orchestration state.
  - disabled: action blocked by lock, deps, missing token, or release gate.

## Output Format

```md
## Orchestration UI Spec
- Entities:
- State transitions:
- Ownership/provenance:
- Gates/blockers:
- Actions:
- State matrix:
```

## Forbidden

- Do not bypass lock protocol in the UI.
- Do not hide stale index/lock warnings.
- Do not let federation UI write directly to `wiki/` or `raw/`.
- Do not merge read-only status and write action affordances.

## See Also

- data-dense-dashboard-design
- ai-product-ux
