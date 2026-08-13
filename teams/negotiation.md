---
title: Team negotiation — Negotiation strategy, deal structure, and legal close
type: team
roles: [negotiator, lawyer, cfo]
curation: human
protected: true
created: 2026-05-09
---

# Team negotiation

Negotiation strategy, deal structure, and legal close.

## Roles
- **negotiator** ([roles/negotiator](../roles/negotiator.md)) — Переговорная стратегия, BATNA, ZOPA, тактика — ведёт переговоры
- **lawyer** ([roles/lawyer](../roles/lawyer.md)) — Юридическая структура сделки, договор — закрывает юридически
- **cfo** ([roles/cfo](../roles/cfo.md)) — Финансовая структура, оценка, pricing — считает экономику

## When to use
Используй для задач, связанных с переговорами — коммерческими,
партнёрскими, M&A, трудовыми или любыми другими.

Типичные сценарии:
- Подготовка к переговорам с инвестором (negotiator primary)
- Согласование условий партнёрского договора (negotiator + lawyer council)
- Структурирование M&A сделки (cfo + lawyer + negotiator council)
- Скрипт переговоров о цене (negotiator primary)
- Term sheet review (lawyer + cfo council)

## Council protocol

Когда задача адресуется через `mode: council` с `council: [team:negotiation]`:

1. Каждая роль получает задание независимо — не читает ответы коллег до завершения.
2. Каждая роль пишет своё мнение в `council/<task-id>/<role>.md`.
3. После того как все роли отписались, `arbiter` запускает `brain-council synthesize <id>`.
4. `arbiter` читает все мнения и пишет `synthesis.md` — финальный ответ.
5. Если synthesis предполагает действия — они декомпозируются в новые задачи.

## Examples
- `council: [team:negotiation] — подготовка к M&A переговорам`
- `council: [negotiator, lawyer] — финальный раунд переговоров`
- `council: [team:negotiation] — структурирование инвестиционного раунда`
