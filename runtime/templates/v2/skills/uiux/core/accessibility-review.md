---
name: accessibility-review
version: 0.1.0
last_updated: 2026-05-07
status: active
owner_role: designer
group: core
applies_to: [designer, developer, reviewer]
invoked_by: [designer, developer, reviewer]
consumed_by: [designer, developer, reviewer]
trigger: Use for any interactive UI, dashboard, table, control bar, form, modal, or status surface.
requires: [ui-spec]
forbidden_zones: [legal-compliance-certification, implementation-internals]
output_format: structured-md
max_lines: 200
---

## Trigger

Run this before handoff and again during review for any user-facing UI change.

## Inputs

- UI spec or screenshot.
- Target controls and keyboard paths.
- Known contrast or layout constraints.

## Checklist

- Check text contrast, focus visibility, keyboard order, and hit targets.
- Ensure status is not communicated by color alone.
- Check labels for icon-only controls and destructive actions.
- Verify tables can be scanned without horizontal ambiguity.
- Define the UI state matrix:
  - empty: meaningful empty state.
  - loading: announced or visibly stable.
  - error: readable and actionable.
  - success: perceivable confirmation.
  - disabled: reason is discoverable.

## Output Format

```md
## Accessibility Review
- Blocking issues:
- Fix before build:
- Verify with:
```

## Forbidden

- Do not claim WCAG compliance certification.
- Do not waive keyboard access for core workflows.
- Do not rely on color alone.

## See Also

- design-system-guard
- visual-regression-checklist
