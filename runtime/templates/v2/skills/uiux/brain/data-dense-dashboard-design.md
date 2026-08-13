---
name: data-dense-dashboard-design
version: 0.1.0
last_updated: 2026-05-07
status: active
owner_role: designer
group: brain
applies_to: [designer, product, developer]
invoked_by: [product, designer, developer, reviewer]
consumed_by: [designer, developer, reviewer]
trigger: Use when designing Brain dashboards, queues, tables, filters, counters, or status-heavy screens.
requires: [information-architecture]
forbidden_zones: [marketing-hero-layouts, decorative-cards, hidden-release-blockers]
output_format: structured-md
max_lines: 200
---

## Trigger

Run this for Brain screens where the operator must scan many tasks, locks,
agents, providers, gates, or logs repeatedly.

## Inputs

- IA map and target data entities.
- Current dashboard or visual shell constraints.
- Priority of scan, compare, filter, and act workflows.

## Checklist

- Optimize for repeated scanning, not first-time explanation.
- Keep primary blockers and stale states visible without scrolling.
- Use tables for repeated records and compact cards only for summaries.
- Provide filters before adding new pages.
- Define the UI state matrix:
  - empty: show the next useful setup/action.
  - loading: preserve table dimensions.
  - error: localize the failed data source.
  - success: default dense operational view.
  - disabled: explain blocked controls inline.

## Output Format

```md
## Data-Dense Dashboard Spec
- Data hierarchy:
- Summary counters:
- Table columns:
- Filters:
- Blocker visibility:
- State matrix:
```

## Forbidden

- Do not create landing-page hero sections.
- Do not use decorative nested cards for operational records.
- Do not hide release blockers, stale locks, or provider failures.
- Do not make a one-color theme.

## See Also

- information-architecture
- orchestration-ui-patterns
