---
name: ux-task-framing
version: 0.1.0
last_updated: 2026-05-07
status: active
owner_role: designer
group: core
applies_to: [designer, product]
invoked_by: [product, designer]
consumed_by: [designer, developer, reviewer]
trigger: Use when a UI task needs a design brief translated from an existing PRD or product brief.
requires: [prd]
forbidden_zones: [success-metrics, scope-changes, business-priority]
output_format: structured-md
max_lines: 200
---

## Trigger

Run this before designing a new screen, workflow, or component when the product
intent exists but the UI problem is still underspecified.

## Inputs

- PRD, product brief, task acceptance, or council synthesis.
- Target users and known workflow constraints.
- Current Brain surface or comparable local pattern.

## Checklist

- State the operator job-to-be-done in one sentence.
- Extract constraints without inventing new scope.
- Identify primary action, secondary actions, and irreversible actions.
- List unknowns for product instead of answering them.
- Define the UI state matrix:
  - empty: what appears before data exists.
  - loading: what is stable while data refreshes.
  - error: what the operator can do next.
  - success: what completion looks like.
  - disabled: why action is unavailable.

## Output Format

```md
## UI Brief
- User/job:
- Surface:
- Primary action:
- Constraints:
- Open product questions:
- State matrix:
```

## Forbidden

- Do not set product metrics.
- Do not expand scope or invent new user segments.
- Do not choose implementation details.

## See Also

- workflow-design
- information-architecture
