---
name: ui-critique
version: 0.1.0
last_updated: 2026-05-07
status: active
owner_role: designer
group: core
applies_to: [designer, reviewer]
invoked_by: [designer, reviewer, product]
consumed_by: [designer, developer, reviewer]
trigger: Use after a UI proposal or implementation exists and needs heuristic critique.
requires: [ui-spec-or-screenshot]
forbidden_zones: [rewriting-product-scope, implementation-prescription]
output_format: structured-md
max_lines: 200
---

## Trigger

Run this as a critique pass, not as the first design step.

## Inputs

- UI proposal, screenshot, or rendered page.
- Intended workflow and acceptance criteria.
- Known constraints.

## Checklist

- Check hierarchy, affordance, consistency, density, and cognitive load.
- Identify where the next action is unclear.
- Separate blocking issues from preference.
- Prefer concrete fixes tied to user tasks.
- Define the UI state matrix:
  - empty: is the first useful action clear?
  - loading: does layout avoid jump?
  - error: is recovery obvious?
  - success: is completion visible?
  - disabled: is the reason legible?

## Output Format

```md
## UI Critique
- P0/P1 issues:
- Concerns:
- Suggested edits:
- Verdict:
```

## Forbidden

- Do not critique taste without a task impact.
- Do not replace product decisions.
- Do not prescribe code internals.

## See Also

- accessibility-review
- workflow-design
