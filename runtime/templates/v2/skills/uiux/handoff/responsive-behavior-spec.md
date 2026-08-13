---
name: responsive-behavior-spec
version: 0.1.0
last_updated: 2026-05-07
status: active
owner_role: designer
group: handoff
applies_to: [designer, developer, reviewer]
invoked_by: [designer, developer, reviewer]
consumed_by: [developer, reviewer]
trigger: Use when UI must work across desktop, tablet, narrow desktop, or mobile widths.
requires: [frontend-handoff-spec]
forbidden_zones: [framework-choice, css-class-names]
output_format: structured-md
max_lines: 200
---

## Trigger

Run this for dashboards, tables, toolbars, cards, or controls that can overflow,
wrap, clip, or become unreadable at smaller widths.

## Inputs

- Handoff spec.
- Content lengths and data density.
- Target viewport assumptions.

## Checklist

- Define desktop, narrow, tablet, and mobile behavior.
- Mark which columns collapse, wrap, hide, or become details.
- Keep critical actions reachable.
- Prevent text overlap, clipping, and layout shifts.

## Output Format

```md
## Responsive Behavior
- Desktop:
- Narrow:
- Tablet:
- Mobile:
- Overflow handling:
- Must-not-break:
```

## Forbidden

- Do not solve overflow by shrinking font with viewport width.
- Do not hide blockers or destructive actions without an alternate path.
- Do not prescribe CSS implementation details.

## See Also

- data-dense-dashboard-design
- visual-regression-checklist
