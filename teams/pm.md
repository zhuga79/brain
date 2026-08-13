---
title: Team pm — Project and product management, delivery rhythm
type: team
roles: [pm, product, delivery]
curation: human
protected: true
created: 2026-05-09
---

# Team pm

Project and product management, delivery rhythm.

## Roles
- **pm** ([roles/pm](../roles/pm.md)) — Scope/time/budget/risk, status, RAID — управляет проектом
- **product** ([roles/product](../roles/product.md)) — Discovery, приоритизация, PRD, метрики — определяет что делать
- **delivery** ([roles/delivery](../roles/delivery.md)) — Ритмы, разблокировка, WIP, flow metrics — обеспечивает поток

## When to use
Используй для задач планирования, приоритизации и управления
потоком работы в проекте.

Типичные сценарии:
- Приоритизация беклога (product primary)
- Оценка рисков и сроков (pm primary)
- Устранение блокеров в работе команды (delivery primary)
- Написание PRD (product primary, pm консультирует по срокам)
- Квартальное планирование (council всей команды)

## Council protocol

Когда задача адресуется через `mode: council` с `council: [team:pm]`:

1. Каждая роль получает задание независимо — не читает ответы коллег до завершения.
2. Каждая роль пишет своё мнение в `council/<task-id>/<role>.md`.
3. После того как все роли отписались, `arbiter` запускает `brain-council synthesize <id>`.
4. `arbiter` читает все мнения и пишет `synthesis.md` — финальный ответ.
5. Если synthesis предполагает действия — они декомпозируются в новые задачи.

## Examples
- `council: [team:pm] — квартальное планирование`
- `council: [product, pm] — приоритизация следующего спринта`
- `council: [team:pm] — post-mortem инцидента`
