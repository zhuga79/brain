---
title: Decision — Следующий цикл: эксплуатация инверсии, не новые функции
type: decision
created: 2026-08-14
updated: 2026-08-14
curation: agent
protected: false
source_policy: advisory
tags: [decision, architecture, publish, operating-model, roadmap]
sources: []
related: [decision-public-source-of-truth, decision-runtime-core-boundaries, decision-role-model-routing, decision-corrective-recurrence, decisions-log]
visibility: public
---

# Decision: следующий цикл — эксплуатация инверсии

**Статус:** принято
**Роль:** architect (`grok-4.6-cto`)
**Родитель:** [[decision-public-source-of-truth]]
**Очередь:** `t-2026-08-14-*` в `tasks/active.md`

## Решение

До конца этого цикла **не начинаем новых продуктовых функций** (дашборд,
федерация, скиллы, витрина). Единственная цель: живой Brain работает так,
как уже записано в [[decision-public-source-of-truth]].

Критерий готовности цикла — не «тикеты закрыты», а четыре факта:

1. Процесс агента читает роли, доктрины и код из системного чекаута
   (`BRAIN_SYSTEM_PATH`), а `~/brain` — только слой данных.
2. В рабочем дереве `~/brain` нет второй копии `runtime/`, `tests/`,
   `roles/`, `teams/`, `doctrine/`, `skills/`, `spec/`.
3. Публичный репозиторий гоняет CI на каждый PR.
4. Установленный `~/.local/bin` совпадает с системным деревом; `brain-status`
   не пишет `Core: unpackaged` с путём из приватного дерева.

Пока любого из четырёх нет, ADR об инверсии описывает намерение, а не
устройство.

## Что измерено 2026-08-14

| Факт | Значение |
|---|---|
| Очередь | 0 open / 408 done |
| `BRAIN_SYSTEM_PATH` в живой сессии | пусто |
| `brain-status` | `Core: unpackaged (.../Brain/files/runtime/lib)` |
| Приватное дерево | содержит `runtime/`, `roles/`, `tests/`, `docs/` и данные |
| Публичный `master` | squash `3f58d31`, PRIVATE, 0 форков |
| Приватный HEAD | `2c0a958` (уже не тот коммит, что public) |
| Установленный `brain-task` | всё ещё передаёт `--client` в Python, который флаг снял |
| Провайдеры | 20/30 unavailable, health cache от 2026-08-13T11:09Z |
| Branch protection / rulesets | 403 на Free/private |

Два дерева уже расходятся. Каждый следующий коммит в `~/brain/runtime`
увеличивает ложь.

## Почему не фичи

Инверсия обещает контрибьюторам: PR в `zhuga79/brain` — это источник.
Сегодня правка в публичном репозитории не попадает в живой процесс, пока
кто-то руками не скопирует дерево. Обратное тоже верно: агенты пишут
систему в приватный репозиторий, и public отстаёт. Это ровно тот тупик,
из-за которого снесли `brain-publish`.

Новые экраны дашборда на этом контуре — работа в никуда.

## Порядок работ

```
reinstall-cli ─────────────────────────────────┐
wire-system-path → private-drop-system         ├─ цикл закрыт
                 → single-write-path           │
public-ci ─────────────────────────────────────┘
package-core          (можно параллельно с reinstall)
guard-history-allow   (можно параллельно)
provider-health       (можно параллельно)
queue-hygiene         (можно сразу)
user-hp-sync          (interactive, оператор)
```

`private-drop-system` не стартует, пока `wire-system-path` не доказан:
снятие `runtime/` из `~/brain` при пустом `BRAIN_SYSTEM_PATH` гасит
инстанс.

## Что сознательно не берём

- Открытие репозитория в public — пока нет CI и пока private tree несёт
  систему, смена видимости снова публикует не тот контракт.
- Восстановление 403-коммитной истории. Squash уже принят: утечка в
  `brain-backup` важнее blame.
- Branch protection до GitHub Pro или до public. 403 зафиксирован.
- Клиентские дела в корневой очереди. Граница `validate_queue_scope`
  остаётся.
- Новые роли, скиллы, вкладки дашборда, федерация.

## Риски

- Снятие системных путей из `~/brain` ломает привычку «править здесь».
  Митигация: сначала проводка `BRAIN_SYSTEM_PATH`, потом удаление, с
  откатом «вернуть каталоги из git history».
- `user-hp` после filter-repo не обновлён. Локальные клоны расходятся.
  Это не блокирует цикл, но блокирует любой push в старый remote.
- 20 мёртвых провайдеров делают council и диверсификацию reviewer/arbiter
  лотереей. Чинится отдельно, не смешивается с корнями.

## Альтернатива, которая отвергнута

Оставить один корень «пока удобно» и считать public витриной. Это вариант
(в) из [[decision-public-source-of-truth]]. Он честен только если откатить
инверсию в ADR. Откат дороже, чем довести проводку: код двух корней уже
написан и покрыт тестами.
