---
name: usability-test-script
version: 0.1.0
last_updated: 2026-05-07
status: draft
owner_role: product
group: handoff
applies_to: [product, designer, growth-analyst]
invoked_by: [product, designer]
consumed_by: [product, designer, growth-analyst]
trigger: Use when real operator workflows and test participants are available.
requires: [real-users, task-scenarios]
forbidden_zones: [pretend-user-testing, sample-size-claims]
output_format: structured-md
max_lines: 200
---

## Trigger

Draft until Brain has real operator workflows to test.

## Inputs

- Target workflow and success criteria.
- Participant profile.
- Prototype or implemented surface.

## Checklist

- Define task scenario and starting state.
- Capture success, hesitation, error, and recovery.
- Separate observation from interpretation.
- Involve growth-analyst before making sample-size claims.

## Output Format

```md
## Usability Test Script
- Scenario:
- Participant:
- Tasks:
- Observations:
- Decisions:
```

## Forbidden

- Do not invent user evidence.
- Do not make statistical claims from anecdotal tests.
- Do not activate before real operator workflows exist.

## See Also

- ux-task-framing
- workflow-design
