---
title: Team engineering — Software design, implementation, and review
type: team
roles: [architect, developer, reviewer]
curation: human
protected: true
created: 2026-05-09
---

# Team engineering

Software design, implementation, and review.

## Roles
- **architect** ([roles/architect](../roles/architect.md)) — Проектирование, декомпозиция, ADR — принимает архитектурные решения
- **developer** ([roles/developer](../roles/developer.md)) — Реализация по плану, написание кода по спецификации
- **reviewer** ([roles/reviewer](../roles/reviewer.md)) — Критика кода и решений, code review с позиции другого провайдера

## When to use
Используй эту команду для задач, связанных с разработкой программного
обеспечения — от архитектуры до реализации и проверки качества кода.

Типичные сценарии:
- Проектирование новой системы или сервиса (architect primary)
- Реализация фичи по PRD (developer primary, architect консультирует)
- Code review перед мержем в main (reviewer primary)
- Рефакторинг кодовой базы (council architect + reviewer)
- Технические ADR (Architecture Decision Records)

## Council protocol

Когда задача адресуется через `mode: council` с `council: [team:engineering]`:

1. Каждая роль получает задание независимо — не читает ответы коллег до завершения.
2. Каждая роль пишет своё мнение в `council/<task-id>/<role>.md`.
3. После того как все роли отписались, `arbiter` запускает `brain-council synthesize <id>`.
4. `arbiter` читает все мнения и пишет `synthesis.md` — финальный ответ.
5. Если synthesis предполагает действия — они декомпозируются в новые задачи.

## Examples
- `council: [team:engineering] — разработка новой фичи с нуля`
- `council: [team:engineering] — review архитектурного решения`
- `council: [architect, reviewer] — только проектирование, без developer`
