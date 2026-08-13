---
name: ai-product-ux
version: 0.1.0
last_updated: 2026-05-07
status: active
owner_role: designer
group: brain
applies_to: [designer, product, developer, reviewer]
invoked_by: [product, designer, developer, reviewer]
consumed_by: [designer, developer, reviewer]
trigger: Use when UI must expose model uncertainty, provider limits, fallback, handoff, or trust boundaries.
requires: [ux-task-framing]
forbidden_zones: [hiding-model-errors, autonomous-unsafe-writes, fake-certainty]
output_format: structured-md
max_lines: 200
---

## Trigger

Run this for any interface involving LLM agents, provider status, quota limits,
handoff artifacts, model confidence, or generated recommendations.

## Inputs

- Provider/role matrix and known fallback policy.
- User decision that depends on model output.
- Error and limit modes.

## Checklist

- Show what model/role produced the result when it matters.
- Separate facts, recommendations, and unverified model inferences.
- Make fallback/handoff status visible and auditable.
- Surface limits without making quota errors look like user mistakes.
- Define the UI state matrix:
  - empty: no model output yet.
  - loading: model/agent is working.
  - error: quota, context, auth, policy, or provider failure.
  - success: result with provenance.
  - disabled: missing auth, role, provider, or prerequisite.

## Output Format

```md
## AI Product UX Spec
- Trust boundary:
- Provenance display:
- Error/limit handling:
- Fallback/handoff:
- State matrix:
```

## Forbidden

- Do not hide model uncertainty or source gaps.
- Do not present generated output as human-approved.
- Do not create a "magic" auto-fix path for protected writes.
- Do not expose tokens/secrets in URLs, logs, or screenshots.

## See Also

- orchestration-ui-patterns
- microcopy-coordination
