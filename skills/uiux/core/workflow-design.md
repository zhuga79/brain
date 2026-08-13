---
name: workflow-design
version: 0.1.0
last_updated: 2026-05-07
status: active
owner_role: designer
group: core
applies_to: [designer]
invoked_by: [product, designer, developer]
consumed_by: [designer, developer, reviewer]
trigger: Use when a UI change introduces or changes a multi-step operator workflow.
requires: [ux-task-framing]
forbidden_zones: [api-shapes, database-schema, implementation-sequencing]
output_format: structured-md
max_lines: 200
---

## Trigger

Run this for flows with more than one step, any destructive action, or any path
that can be interrupted by locks, provider limits, or validation failures.

## Inputs

- UI brief.
- Existing command/API behavior.
- Known failure modes and permission gates.

## Checklist

- Map happy path as numbered steps.
- Add recovery paths for cancellation, stale data, invalid input, and retry.
- Mark destructive steps and required confirmations.
- Keep navigation reversible where possible.
- Define the UI state matrix:
  - empty: first-run or no-task case.
  - loading: data fetch, SSE refresh, or long command.
  - error: validation, auth, lock, provider, or network failure.
  - success: visible confirmation and next action.
  - disabled: unmet dependency or missing permission.

## Output Format

```md
## Workflow
1. Step
## Edge Cases
- Case -> UI response
## State Matrix
```

## Forbidden

- Do not hide errors behind generic failure copy.
- Do not remove operator control from irreversible actions.
- Do not decide backend implementation.

## See Also

- ai-product-ux
- frontend-handoff-spec
