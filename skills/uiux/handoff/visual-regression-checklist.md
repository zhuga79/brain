---
name: visual-regression-checklist
version: 0.1.0
last_updated: 2026-05-07
status: draft
owner_role: developer
group: handoff
applies_to: [designer, developer, reviewer]
invoked_by: [developer, reviewer]
consumed_by: [developer, reviewer]
trigger: Use after Playwright or screenshot infrastructure exists for UI verification.
requires: [playwright-screenshot-infra]
forbidden_zones: [manual-only-approval, screenshot-free-visual-claims]
output_format: structured-md
max_lines: 200
---

## Trigger

Draft until the project has stable browser screenshot tooling.

## Inputs

- Implemented UI surface.
- Viewports and states to capture.
- Known visual risks.

## Checklist

- Capture desktop and mobile viewports.
- Check blank canvas, clipping, overlap, contrast, and critical states.
- Verify empty/loading/error/success/disabled states when possible.

## Output Format

```md
## Visual Regression Checklist
- Commands:
- Viewports:
- States:
- Screenshots:
- Failures:
```

## Forbidden

- Do not claim visual verification without rendered evidence.
- Do not block Phase 12 active skills on missing infra.

## See Also

- responsive-behavior-spec
- accessibility-review
