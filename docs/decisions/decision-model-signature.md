---
title: Decision — Model signature contract
type: decision
created: 2026-08-31
updated: 2026-08-31
curation: agent
protected: false
source_policy: advisory
tags: [decision, tasks, completion, model-signature]
sources: []
related: [decision-runtime-core-boundaries, about-brain, architecture-overview]
visibility: public
---

# Decision: Model signature contract

**Статус:** принято
**Задача:** `t-2026-08-14-model-signature-contract-align`
**Роль:** developer

## Решение

Подпись модели при закрытии задачи — доменный инвариант, а не настройка
адаптера. Один модуль `brain_core.model_signature` резолвит значение
`model:` для CLI (`brain-task`, `brain-shell`), MCP `complete_task`,
dashboard `POST /api/tasks?action=complete`, `brain_app.queue.complete`
и `brain_workspace.complete_local_task`.

Нормальное закрытие требует versioned идентификатор
`provider-model-version` (`openai-gpt-5.4`, `claude-opus-4-8`,
`gemini-2.5-pro`, `grok-4.6`). Источник: `--model` / аргумент, иначе
`$BRAIN_AGENT_MODEL`.

Литерал `unsigned` — legacy escape hatch. Он не является умолчанием.
Чтобы записать его, нужен явный opt-in:

- флаг `--allow-unsigned` (CLI, workspace, shell)
- query `allow_unsigned=1` (dashboard)
- аргумент `allow_unsigned=True` (MCP / Python)
- либо `$BRAIN_ALLOW_UNSIGNED_MODEL=1`

Hatch обязан оставить audit `model-unsigned` в журнале. Адаптеры не
подставляют `unsigned` молча. `$BRAIN_REQUIRE_MODEL` больше не
переключает политику: требование подписи стало умолчанием.

Писатель `brain_core.taskfile` по-прежнему записывает переданную строку:
архивные `done.md` с историческим `model: unsigned` и уже подписанные
записи остаются читаемыми. Политика живёт в резолвере, который вызывают
адаптеры до записи.

## Следствия

- Dashboard complete без модели — отказ, а не `model: unsigned`.
- MCP принимает `$BRAIN_AGENT_MODEL`, как CLI.
- `probe-model` / `test-model` без числовой версии не являются подписью.
