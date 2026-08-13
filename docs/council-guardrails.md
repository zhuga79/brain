---
title: Council Guardrails
slug: council-guardrails
type: concept
tags: [council, process, guardrails]
source_policy: ignored
created: 2026-05-03
updated: 2026-05-03
visibility: public
---

# Council Guardrails

Минимальный машинопроверяемый checklist готовности совета Brain.
Не используем LLM для проверки качества — только структурные проверки.

## Команда проверки

```bash
brain-council check <task-id>
```

Возвращает `status: OK` или `status: FAIL` с перечнем ошибок.
Предупреждения (WARN) не блокируют, но логируются.

## Checklist (machine-checkable)

| # | Проверка | Уровень |
|---|----------|---------|
| 1 | Все role-файлы существуют и не содержат `agent: TODO` | ERROR |
| 2 | `written:` в frontmatter каждой роли — не TODO | ERROR |
| 3 | Секция `## Position` непустая | ERROR |
| 4 | Секция `## Recommendation` непустая | ERROR |
| 5 | `synthesis.md` существует и не содержит `synthesized: TODO` | WARN |
| 6 | Все роли имеют одинаковый `agent:` (solo council) | WARN |

## Допустимые паттерны

### Solo council
Один агент пишет все роли. Допустимо при одиночной оркестрации.
- `brain-council check` выдаёт WARN, не FAIL
- Указывать в логе: `log_op council-solo <id>`
- Ограничение: мнения коррелированы (один LLM = похожие позиции)

### Partial council
Не все роли заполнены. Синтез разрешён через `brain-council synthesize --force`.
- WARN от `check`, не FAIL

### Write-before-read
Каждая роль пишет мнение **до** чтения других мнений.
Это дисциплинарное требование, не техническое — enforce через договорённость.

## Критерии готовности synthesis.md

- Все роли заполнены (нет TODO в `agent`/`written`)
- Секции `## Position`, `## Reasoning`, `## Recommendation` непустые у всех ролей
- `synthesis.md` содержит непустые: Positions TL;DR, Agreement, Decision, Why

## Пример прохождения check

```
$ brain-council check t-my-task
WARN: solo council — all roles written by the same agent: claude-sonnet-4-6-b8c3
---
council check: t-my-task
  roles: 3  errors: 0  warnings: 1
  status: OK
```

## Связанные страницы

- [[workflow-solo-council]] — workflow для solo-оркестрации
- [[roles-overview]] — описание ролей
