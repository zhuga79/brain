---
name: microcopy-coordination
version: 0.1.0
last_updated: 2026-05-07
status: active
owner_role: designer
group: handoff
applies_to: [designer, copywriter, product]
invoked_by: [designer, product, reviewer]
consumed_by: [copywriter, developer, reviewer]
trigger: Use when labels, errors, empty states, warnings, confirmations, or button text need copywriter ownership.
requires: [ux-task-framing]
forbidden_zones: [final-copy, brand-voice-decision, legal-wording]
output_format: structured-md
max_lines: 200
---

## Trigger

Run this before frontend handoff when text can change layout, meaning, trust, or
operator confidence.

## Inputs

- UI brief and workflow.
- Current draft labels or placeholder copy.
- Space constraints and severity levels.

## Checklist

- Identify text slots that need copywriter decision.
- Include context, severity, character constraints, and target action.
- Spawn or specify a copywriter task/brief.
- Mark `microcopy: not-applicable` only when no user-visible text changes.

## Output Format

```md
## Microcopy Brief
- Copywriter task:
- Text slots:
- Context:
- Constraints:
- Approval needed before:
```

## Forbidden

- Do not write final copy.
- Do not decide legal/compliance wording.
- Do not finalize frontend handoff while required copy is open.

## See Also

- frontend-handoff-spec
- ai-product-ux
