---
name: frontend-handoff-spec
version: 0.1.0
last_updated: 2026-05-07
status: active
owner_role: designer
group: handoff
applies_to: [designer, developer]
invoked_by: [designer, developer, reviewer]
consumed_by: [developer, reviewer]
trigger: Use when a UI design decision must be handed to developer for implementation.
requires: [workflow-design, microcopy-coordination]
forbidden_zones: [component-internals, css-class-names, api-shapes]
output_format: structured-md
max_lines: 200
---

## Trigger

Run this when design intent is ready to become an implementation task.

## Inputs

- UI brief, workflow, IA, and relevant Brain-specific skills.
- Microcopy status or explicit `microcopy: not-applicable`.
- Acceptance criteria and target files if known.

## Checklist

- List components, states, actions, and data needs.
- Identify API/data assumptions as questions, not decisions.
- Include responsive and accessibility requirements.
- Include verification expectations.

## Output Format

```md
## Frontend Handoff
- Components:
- States:
- Actions/events:
- Data/API questions:
- Responsive:
- Accessibility:
- Verification:
- Microcopy:
```

## Forbidden

- Do not choose internal component names.
- Do not prescribe CSS class names.
- Do not finalize handoff while microcopy is unresolved.

## See Also

- responsive-behavior-spec
- accessibility-review
