---
title: Team marketing — Positioning, messaging, and growth analytics
type: team
roles: [strategist, copywriter, growth-analyst]
curation: human
protected: true
created: 2026-05-09
---

# Team marketing

Positioning, messaging, and growth analytics.

## Roles
- **strategist** ([roles/strategist](../roles/strategist.md)) — Позиционирование, ICP, GTM — определяет кому и что продавать
- **copywriter** ([roles/copywriter](../roles/copywriter.md)) — Тексты лендингов, рассылок, постов — пишет для людей
- **growth-analyst** ([roles/growth-analyst](../roles/growth-analyst.md)) — Юнит-экономика, A/B тесты, аналитика роста

## When to use
Используй для задач вывода продукта на рынок, создания контента
и анализа эффективности маркетинговых активностей.

Типичные сценарии:
- GTM для нового продукта (strategist primary)
- Написание лендинга или рассылки (copywriter primary, strategist консультирует)
- Анализ CAC/LTV, A/B тест (growth-analyst primary)
- Ребрендинг или смена позиционирования (council всей команды)
- Контент-план для соцсетей (copywriter + strategist council)

## Council protocol

Когда задача адресуется через `mode: council` с `council: [team:marketing]`:

1. Каждая роль получает задание независимо — не читает ответы коллег до завершения.
2. Каждая роль пишет своё мнение в `council/<task-id>/<role>.md`.
3. После того как все роли отписались, `arbiter` запускает `brain-council synthesize <id>`.
4. `arbiter` читает все мнения и пишет `synthesis.md` — финальный ответ.
5. Если synthesis предполагает действия — они декомпозируются в новые задачи.

## Examples
- `council: [team:marketing] — запуск нового продукта`
- `council: [strategist, copywriter] — переработка лендинга`
- `council: [team:marketing] — ревью маркетинговой стратегии`
