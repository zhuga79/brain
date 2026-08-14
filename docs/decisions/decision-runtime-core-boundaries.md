---
title: Decision — Runtime Core: границы модулей и владельцы записи
type: decision
created: 2026-08-10
updated: 2026-08-14
curation: agent
protected: false
source_policy: advisory
tags: [decision, architecture, runtime, tasks, concurrency]
sources: []
related: [about-brain, architecture-overview, decision-llm-stack, decision-post-inversion-cycle, decision-public-source-of-truth, decision-role-model-routing, decisions-log, workflow-solo-council]
visibility: public
---

# Decision: Runtime Core — границы модулей и владельцы записи

**Статус:** принято, реализовано частично
**Задача:** `t-2026-08-10-brain-runtime-48-12k-loc-49-c`
**Роль:** architect (`operator-architect-1112723` → `operator-architect-1119019` по handoff)

## Решение

У Brain есть один корневой контракт: **состояние очереди нельзя менять из
произвольных CLI/MCP-обвязок**. Доменные инварианты живут в `runtime/lib`,
а `runtime/bin/*` и MCP-инструменты должны быть тонкими адаптерами.

Это решение не означает «всё состояние в одном writer-е». Граница уже
точнее:

- корневая очередь `tasks/active.md` + `tasks/done.md` принадлежит
  `brain_core.taskfile`;
- PRD-коммит в корневую очередь идёт через `brain_core.prdfile` и использует
  тот же queue lock;
- локальные workspace-файлы `TASKS.md` + `LOG.md` имеют **отдельную**
  workspace-транзакцию в `brain_workspace.py`;
- routing `role -> command` решается в одном месте:
  `brain_provider.resolve_for_role()`;
- split-root границы системы и данных валидируются и защищаются setup/hook-ами,
  а не договорённостью в prose.

## Что уже реализовано

### 1. Корневая очередь имеет одного писателя

`runtime/lib/brain_core/taskfile.py` — единственный writer для
`tasks/active.md` и `tasks/done.md`. Он держит общий queue lock, пишет через
`tmp + fsync + os.replace` и ведёт completion journal для recovery после
падения между `done.md` и `active.md`.

Практическое следствие: claims про «единого writer-а» теперь допустимы только
для **корневой очереди**, но не для всего Brain.

### 2. `brain-task` стал фасадом, а не отдельной реализацией

`runtime/bin/brain-task` вызывает `brain_core.taskfile` и требует подпись
модели при completion (`--model` или `BRAIN_AGENT_MODEL`; `BRAIN_REQUIRE_MODEL=1`
делает это обязательным).

Ownership тоже проверяется в домене: чужой агент не должен release/complete
задачу, если lock принадлежит другому.

### 3. PRD больше не пишет `active.md` напрямую

`runtime/bin/brain-prd` коммитит subtasks через `brain_core.prdfile`.
`prdfile` нормализует ids, обновляет PRD, добавляет subtasks в active queue и
делает это под тем же queue lock, что и `taskfile`.

Это отдельный transaction coordinator, а не второй произвольный writer.

### 4. MCP queue tools выровнены с CLI

`runtime/mcp/tools_tasks.py` больше не редактирует очередь вручную.
Инструменты очереди идут через `brain_app.queue`, а тот опирается на
`brain_core.taskfile`.

Следствие: установленный MCP и shell CLI должны работать с тем же контрактом
очереди, а drift между ними считается дефектом установки/пакетирования, а не
нормой.

### 5. Workspace-очереди намеренно отделены от корневой

Локальные workspace-задачи (`BRAIN.md` + `TASKS.md` + `LOG.md`) не используют
корневой writer. У них отдельная транзакция в `brain_workspace.py`:
workspace lock, атомарные записи и recovery journal для пары
`TASKS.md` / `LOG.md`.

Это другой bounded context, а не нарушение решения.

### 6. Routing command availability централизован

Резолв роли идёт через `brain_provider.resolve_for_role()`.
Контракт такой:

- `override` сильнее конфига;
- затем идут кандидаты из `config/routing.json`;
- missing/non-executable local command пропускается с явным warning;
- declared `execution: virtual|remote` остаётся допустимым кандидатом;
- если ни один кандидат не доступен, возвращается `defaults.cli` с warning,
  а не silent crash.

Это именно контракт availability, а не обещание, что любой кандидат можно
запустить без внешних зависимостей.

### 7. Split-root границы стали исполняемыми

В двухкорневом режиме системные пути (`runtime/`, `tests/`, `roles/`,
`teams/`, `doctrine/`, `skills/`, `spec/`, `docs/`, `config/`, `MEMORY.md`)
принадлежат system checkout. Data root не должен нести их вторую живую копию.

`setup-brain-v2.sh`, `brain-validate` и pre-commit write-path guard теперь
рассматривают system shadow в data root как ошибку эксплуатации.

### 8. Release gates описываются полным набором проверок

Текущий gate для system repo: smoke suite + pytest в CI и в локальном
pre-commit, плюс `brain-validate` / `brain-lint` в эксплуатационном цикле.
Документация не должна больше обещать «зелёный status» по одному smoke-only
сигналу.

## Что это решение не утверждает

- Оно **не** говорит, что весь Brain уже сведён к одному доменному ядру.
- Оно **не** говорит, что любой MCP tool уже тонкий фасад: это верно для
  queue-path, но не для всех прочих операций.
- Оно **не** отменяет наличие отдельных transaction boundaries у workspace и
  других file-backed контуров.
- Оно **не** разрешает править system assets в `~/brain`: для split-root это
  уже нарушение write path.

## Оставшийся архитектурный долг

1. Не каждый MCP-инструмент живёт на том же уровне зрелости, что queue tools.
2. Release health всё ещё складывается из нескольких сигналов, а не из одного
   агрегированного статуса.
3. Исторические bash-фасады сохранены и должны продолжать оставаться тонкими.
4. Документация и handoff обязаны различать root queue transaction,
   PRD queue commit и workspace local transaction; слово `writer` без
   уточнения больше недостаточно.
