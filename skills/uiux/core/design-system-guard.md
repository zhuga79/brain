---
name: design-system-guard
version: 0.1.0
last_updated: 2026-05-07
status: active
owner_role: designer
group: core
applies_to: [designer, developer]
invoked_by: [designer, developer, reviewer]
consumed_by: [designer, developer, reviewer]
trigger: Use before adding or changing visual styles, tokens, spacing, typography, or reusable components.
requires: [existing-ui]
forbidden_zones: [css-class-names, framework-choice, build-tooling]
output_format: structured-md
max_lines: 200
---

## Trigger

Run this when a UI task could introduce one-off colors, typography, spacing,
cards, controls, icons, or layout patterns.

## Inputs

- Existing screen or component.
- Current CSS/design tokens.
- Target component or interaction.

## Checklist

- Reuse existing component patterns before adding variants.
- Keep typography proportional to the container and task density.
- Use icons for standard tool actions when available.
- Avoid nested cards and decorative backgrounds in operational tools.
- Define the UI state matrix:
  - empty: placeholder treatment.
  - loading: skeleton or stable placeholder.
  - error: severity color and icon.
  - success: confirmation treatment.
  - disabled: contrast and affordance.

## Output Format

```md
## Design System Guard
- Reused patterns:
- New variants:
- Token impact:
- Risks:
```

## Forbidden

- Do not introduce a one-note palette.
- Do not prescribe internal CSS class names.
- Do not add decorative sections to dense operational screens.

## See Also

- accessibility-review
- ui-critique
