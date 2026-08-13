---
title: Decision — Interactive Surface (human-in-the-loop routing)
type: decision
created: 2026-06-26
updated: 2026-06-26
curation: agent
protected: false
source_policy: advisory
tags: [decision, orchestration, human-in-loop, surface, gate]
sources: []
related: [roles-overview, about-brain, decision-llm-stack]
visibility: public
---

# Decision: Interactive Surface

**Статус:** принято
**Дата:** 2026-06-26
**Автор:** architect (по PM-анализу 2026-06-26)
**Machine mapping:** поля `surface` / `gate` в `tasks/active.md` (см. `tasks/SCHEMA.md`)

## Контекст

Оркестратор (`brain-orchestrator`, `brain-launch`, dashboard) запускает агентов
двумя путями: видимые tmux-окна (`brain-launch` = окно-на-роль) и headless
auto-next в фоне. Сейчас выбор поверхности не привязан к природе задачи.
`brain_handoff_detector` ловит только технические прерывания
(rate-limit/quota), но не семантическую потребность в человеке. Итог:
задачи, исход которых зависит от диалога с человеком (вкус, апрув, факты из
реального мира), могут уехать в headless и «дойти до стены» в середине прогона.

## Решение

Вводим признак поверхности на уровне тикета:

- `surface: headless` (default) — полностью автономно, фон, можно `auto-next`.
- `surface: interactive` — исход зависит от диалога с человеком. Запуск только
  в видимом окне (tmux/терминал/чат). Оркестратор не берёт такую задачу в
  headless auto-next и распознаёт класс до запуска.

Опциональный `gate:` уточняет тип человеческого шлюза (для UI/роутинга/метрик).

## Таксономия (9 типов interactive-задач)

| gate | Тип | Триггер | Почему человек | Дефолт по роли |
|------|-----|---------|----------------|----------------|
| `approval` | Approval / sign-off | release (`brain-release`, v-tег), scope change, security write-gate | необратимо/публично, ответственность на человеке | security, pm |
| `taste` | Субъективный вкус / визуал | `taste-reviewer`, designer verdict, anti-slop | эстетика не верифицируема headless | taste-reviewer, designer |
| `legal` | High-stakes legal/financial | финал договора (lawyer), налоговая позиция (tax-advisor), инвестрешение (cfo), переговоры (negotiator) | юр./фин. liability на человеке | lawyer, tax-advisor, cfo, negotiator |
| `intake` | Ambiguity / priority resolution | размытое «давайте сделаем X» без acceptance; неясный приоритет | без человека acceptance выдумывается → scope creep | product, pm |
| `arbiter` | Council split / арбитраж | arbiter видит несогласие ролей | trade-off — ценностный выбор | arbiter |
| `data` | Real-world факты на вход | renovation (фото/замеры), accountant первичка, stage-map | данных нет в репо, их приносит человек | renovation-planner, accountant |
| `risk` | Risk acceptance | RAID-риск помечен к принятию | принять риск может только владелец | pm |
| `secret` | Secrets / auth / пароли | login, ввод пароля, токен | правило: пароль — только в отдельном видимом окне | — (любой) |
| `curation` | Curation override | правка protected:true / curation:human | контракт курации запрещает авто-перезапись | linter, любой |

## Анти-список (остаётся headless)

Реализация по готовому плану (developer), линт/валидация wiki, brain-index
rebuild, sync-циклы, research-наполнение raw/, генерация черновиков на ревью.

## Дефолтная классификация (когда поле не задано)

Оркестратор выводит surface из role/gate:
- роль кандидат-человека (taste-reviewer, designer-verdict, lawyer, tax-advisor,
  cfo, negotiator, arbiter, accountant, renovation-planner) → кандидат interactive;
- наличие gate: → interactive;
- иначе → headless.
Явно заданное поле всегда побеждает дефолт.

## Последствия / follow-up

- t-2026-06-26-orchestrator-route — запрет headless auto-next для interactive.
- t-2026-06-26-handoff-semantic — детектор маркера NEEDS_HUMAN → видимое окно.
- t-2026-06-26-pilot-design-review — пилот на текущих design-review задачах.
- t-2026-06-26-dashboard-badge — badge surface на dashboard.

## Риски

- Over-tagging: слишком много interactive убьёт автономность. Митигация: узкий
  анти-список headless, дефолт = headless.
- Дрейф дефолтов: список ролей-кандидатов должен жить рядом с роутером и этой
  страницей синхронно. Митигация: single source of truth в роутере, ссылка сюда.
