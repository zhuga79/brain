---
title: Team legal — Contracts, corporate law, and regulatory compliance (Russian law)
type: team
roles: [lawyer, compliance, paralegal]
curation: human
protected: true
created: 2026-05-09
---

# Team legal

Contracts, corporate law, and regulatory compliance (Russian law).

## Roles
- **lawyer** ([roles/lawyer](../roles/lawyer.md)) — Договоры, корпоративное право (ГК РФ), судебные споры, оферты
- **compliance** ([roles/compliance](../roles/compliance.md)) — ФЗ-152, ФЗ-572, 115-ФЗ, 259-ФЗ, ГОСТ — регуляторные процессы
- **paralegal** ([roles/paralegal](../roles/paralegal.md)) — Поиск практики, проверка контрагентов, шаблоны договоров

## When to use
Используй для задач, связанных с российским законодательством, договорным
правом и регуляторными требованиями.

Типичные сценарии:
- Составление и проверка договоров (lawyer primary)
- Compliance-программы (ФЗ-152, 115-ФЗ) (compliance primary)
- Проверка контрагента перед сделкой (paralegal primary)
- Корпоративные документы — устав, решения ОУ (lawyer primary)
- Ответ на запросы регуляторов (lawyer + compliance council)

## Council protocol

Когда задача адресуется через `mode: council` с `council: [team:legal]`:

1. Каждая роль получает задание независимо — не читает ответы коллег до завершения.
2. Каждая роль пишет своё мнение в `council/<task-id>/<role>.md`.
3. После того как все роли отписались, `arbiter` запускает `brain-council synthesize <id>`.
4. `arbiter` читает все мнения и пишет `synthesis.md` — финальный ответ.
5. Если synthesis предполагает действия — они декомпозируются в новые задачи.

## Examples
- `council: [team:legal] — юридическая экспертиза нового продукта`
- `council: [team:legal] — разработка compliance-программы`
- `council: [lawyer, compliance] — ФЗ-152 политика и процессы`
