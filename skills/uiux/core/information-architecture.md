---
name: information-architecture
version: 0.1.0
last_updated: 2026-05-07
status: active
owner_role: designer
group: core
applies_to: [designer]
invoked_by: [product, designer, reviewer]
consumed_by: [designer, developer, reviewer]
trigger: Use when a surface needs navigation, grouping, hierarchy, or progressive disclosure decisions.
requires: [ux-task-framing]
forbidden_zones: [route-implementation, data-model-design]
output_format: structured-md
max_lines: 200
---

## Trigger

Run this when users must scan, compare, filter, or move between related Brain
objects such as tasks, councils, locks, providers, metrics, and logs.

## Inputs

- UI brief or workflow.
- Data entities and their relationships.
- Existing dashboard sections and labels.

## Checklist

- Identify top-level objects and secondary metadata.
- Group by operator decision, not by backend table.
- Prefer dense but readable tables for repeated operational items.
- Put rare details behind disclosure rather than new pages.
- Define the UI state matrix:
  - empty: no records or filters remove all records.
  - loading: stable layout while data arrives.
  - error: which section failed.
  - success: default populated layout.
  - disabled: unavailable filters/actions.

## Output Format

```md
## IA Map
- Section:
- Primary data:
- Secondary data:
- Progressive disclosure:
```

## Forbidden

- Do not create marketing-style navigation for operational tools.
- Do not bury release blockers or lock state.
- Do not invent new domain entities.

## See Also

- data-dense-dashboard-design
- orchestration-ui-patterns
