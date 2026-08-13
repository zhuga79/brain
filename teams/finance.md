---
title: Team finance — Cash flow, accounting, and tax advisory
type: team
roles: [cfo, accountant, tax-advisor]
curation: human
protected: true
created: 2026-05-09
---

# Team finance

Cash flow, accounting, and tax advisory.

## Roles
- **cfo** ([roles/cfo](../roles/cfo.md)) — Cashflow, юнит-экономика, инвест. решения, pricing — финансовая стратегия
- **accountant** ([roles/accountant](../roles/accountant.md)) — Первичка, учёт, закрытие периода — бухгалтерский учёт
- **tax-advisor** ([roles/tax-advisor](../roles/tax-advisor.md)) — Налоговые режимы, НПД/УСН/ОСНО, льготы, валютный контроль

## When to use
Используй для задач финансового планирования, бухгалтерского учёта
и налогового консультирования. При работе с налогами — сначала определи этап (1–4)
по [[doctrine/tax-boundaries]] до выбора primary.

Типичные сценарии:
- Финансовая модель нового продукта (cfo primary)
- Закрытие месяца, ОСВ (accountant primary)
- Выбор налогового режима (tax-advisor primary)
- Cashflow-прогноз на год (cfo + accountant council)
- Пограничные налоговые ситуации (см. doctrine/tax-boundaries этап 3)

## Council protocol

Когда задача адресуется через `mode: council` с `council: [team:finance]`:

1. Каждая роль получает задание независимо — не читает ответы коллег до завершения.
2. Каждая роль пишет своё мнение в `council/<task-id>/<role>.md`.
3. После того как все роли отписались, `arbiter` запускает `brain-council synthesize <id>`.
4. `arbiter` читает все мнения и пишет `synthesis.md` — финальный ответ.
5. Если synthesis предполагает действия — они декомпозируются в новые задачи.

## Examples
- `council: [team:finance] — годовое финансовое планирование`
- `council: [cfo, tax-advisor] — анализ схемы налогообложения`
- `council: [accountant, tax-advisor] — подготовка к налоговой проверке`
