---
title: Team creative — Brand, UX/UI design, and creative direction
type: team
roles: [designer, copywriter, strategist]
curation: human
protected: true
created: 2026-05-09
---

# Team creative

Brand, UX/UI design, and creative direction.

## Roles
- **designer** ([roles/designer](../roles/designer.md)) — UX/UI, brand, design system — создаёт визуальный язык и интерфейсы
- **copywriter** ([roles/copywriter](../roles/copywriter.md)) — Тексты коммуникаций, naming, taglines — голос бренда
- **strategist** ([roles/strategist](../roles/strategist.md)) — Позиционирование и бренд-стратегия — зачем и для кого

## When to use
Используй для задач, связанных с визуальным языком, UX/UI,
брендом и творческой коммуникацией.

Типичные сценарии:
- Разработка нового UI screen или flow (designer primary)
- Создание или обновление design system (designer + reviewer council)
- Naming и brand voice (copywriter + strategist council)
- Проверка нового экрана на соответствие бренду (designer primary)
- Редизайн онбординга (council всей команды + product)

## Council protocol

Когда задача адресуется через `mode: council` с `council: [team:creative]`:

1. Каждая роль получает задание независимо — не читает ответы коллег до завершения.
2. Каждая роль пишет своё мнение в `council/<task-id>/<role>.md`.
3. После того как все роли отписались, `arbiter` запускает `brain-council synthesize <id>`.
4. `arbiter` читает все мнения и пишет `synthesis.md` — финальный ответ.
5. Если synthesis предполагает действия — они декомпозируются в новые задачи.

## Examples
- `council: [team:creative] — редизайн главной страницы`
- `council: [designer, copywriter] — создание нового экрана регистрации`
- `council: [team:creative, product] — обновление design system`
