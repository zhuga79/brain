---
title: Team design-review — UI taste, structure, and implementation readiness
type: team
roles: [product, designer, taste-reviewer, impeccable-reviewer, developer, reviewer]
curation: agent
protected: false
created: 2026-06-25
---

# Team design-review

UI taste, UX structure, and implementation readiness.

## Roles
- **product** ([roles/product](../roles/product.md)) — проверяет цель, аудиторию, JTBD и success criteria.
- **designer** ([roles/designer](../roles/designer.md)) — отвечает за visual system, flow и handoff.
- **taste-reviewer** ([roles/taste-reviewer](../roles/taste-reviewer.md)) — проверяет визуальный вкус, иерархию, rhythm, composition и anti-slop.
- **impeccable-reviewer** ([roles/impeccable-reviewer](../roles/impeccable-reviewer.md)) — проверяет структуру, responsive, a11y, states, motion и implementation readiness.
- **developer** ([roles/developer](../roles/developer.md)) — оценивает реализуемость и blast radius.
- **reviewer** ([roles/reviewer](../roles/reviewer.md)) — ищет риски, regression gaps и нарушение acceptance.

## When to use
Используй для новых UI flows, редизайна, dashboard экранов, design-system
изменений и ревью внешних design-agent практик перед внедрением в Brain.

## Council protocol

Когда задача адресуется через `mode: council` с `council: [team:design-review]`:

1. Каждая роль пишет независимое мнение в `council/<task-id>/<role>.md`.
2. Роли не читают ответы коллег до завершения своих файлов.
3. `arbiter` запускает `brain-council synthesize <id>`.
4. Synthesis фиксирует decision: adopt, adapt, reject или needs-research.
5. Если нужны действия, synthesis декомпозируется в отдельные задачи.

## Examples
- `council: [team:design-review] — review new dashboard shell`
- `council: [taste-reviewer, designer] — visual taste pass`
- `council: [impeccable-reviewer, developer, qa] — responsive/a11y implementation audit`
