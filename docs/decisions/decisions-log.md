---
title: Decisions Log
type: decision
created: 2026-05-03
updated: 2026-09-04
curation: agent
protected: false
source_policy: advisory
tags: [bootstrap]
sources: []
related: []
visibility: public
---

# Decisions Log

Страница для фиксации архитектурных решений.

## Принятые решения

- [[decision-llm-stack]] — выбор стека моделей для ролей Brain (2026-05-03)
- [[prd-t-2026-05-09-code-review-brain-runtime]] — PRD по устранению проблем Brain Runtime после вертикального и горизонтального ревью (2026-05-09)
- [[phase-13-prd]] — Phase 13: handoff journal, provider health, visual workflow (2026-05-07)
- [[decision-runtime-core-boundaries]] — Runtime Core: границы модулей, единый владелец очереди задач, атомарность и локи (2026-08-10)
- [[decision-role-model-routing]] — маршрутизация «роль → модель»: один машинный источник вне wiki/, политика отделена от доступности (2026-08-10)
- [[decision-public-source-of-truth]] — инверсия публикации: системный код живёт в публичном репозитории и является источником, приватное дерево — слой данных; PR принимаются напрямую (2026-08-10)
- [[decision-corrective-recurrence]] — рецидив корректирующей задачи после закрытия заводит новую; воскрешение в окне 72ч невозможно (2026-08-13)
- [[decision-post-inversion-cycle]] — следующий цикл: живая инверсия двух корней, без новых продуктовых функций (2026-08-14)
- [[decision-setup-runtime-pth-and-pytest-pythonpath]] — порт data-root: `.pth` всегда после pip; `pythonpath` в pyproject отклонён (2026-08-31)
- [[decision-model-signature]] — единая политика подписи модели при complete: versioned обязательно, unsigned только явный hatch (2026-08-31)
- [[decision-multi-user-federation]] — federation для команды (идентичность узла, конфликт лока, детерминированное слияние журнала и очередей) + сборка устанавливаемого .deb из канонического источника (2026-09-04)

Связанные страницы: [[about-brain]], [[roles-overview]].
