---
title: Team research — Primary research, market analysis, and evidence synthesis
type: team
roles: [researcher, growth-analyst, reviewer]
curation: human
protected: true
created: 2026-05-09
---

# Team research

Primary research, market analysis, and evidence synthesis.

## Roles
- **researcher** ([roles/researcher](../roles/researcher.md)) — Поиск источников, наполнение raw/ — добывает первичные данные
- **growth-analyst** ([roles/growth-analyst](../roles/growth-analyst.md)) — Юнит-экономика, анализ рынка, A/B — интерпретирует данные
- **reviewer** ([roles/reviewer](../roles/reviewer.md)) — Критика источников и выводов — проверяет качество исследования

## When to use
Используй для задач, требующих поиска и анализа внешних данных,
рыночных исследований и синтеза доказательств.

Типичные сценарии:
- Исследование рынка и конкурентов (researcher primary)
- Анализ данных с web-поиском (researcher + growth-analyst council)
- Проверка источников и достоверности (reviewer primary)
- Наполнение wiki/raw/ фактическими данными (researcher primary)
- Бенчмаркинг продуктов конкурентов (council всей команды)

## Council protocol

Когда задача адресуется через `mode: council` с `council: [team:research]`:

1. Каждая роль получает задание независимо — не читает ответы коллег до завершения.
2. Каждая роль пишет своё мнение в `council/<task-id>/<role>.md`.
3. После того как все роли отписались, `arbiter` запускает `brain-council synthesize <id>`.
4. `arbiter` читает все мнения и пишет `synthesis.md` — финальный ответ.
5. Если synthesis предполагает действия — они декомпозируются в новые задачи.

## Examples
- `council: [team:research] — конкурентный анализ перед запуском`
- `council: [researcher, growth-analyst] — исследование ICP`
- `council: [team:research] — синтез отраслевых отчётов`
