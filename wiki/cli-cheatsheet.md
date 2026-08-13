---
title: Cli Cheatsheet
type: concept
created: 2026-05-03
updated: 2026-05-06
curation: agent
protected: false
source_policy: advisory
tags: [bootstrap]
sources: []
related: []
visibility: public
---

# CLI Cheatsheet

## Основные команды

- `brain-task`                              — очередь задач
- `brain-lock`                              — блокировки
- `brain-lint`                              — аудит wiki
- `brain-validate`                          — проверка контрактов
- `brain-index rebuild`                     — пересборка индекса
- `brain-search "<query>"`                  — BM25-поиск

## Phase 4: Vector + Webhook + Watch

```bash
# Векторный поиск (требует chromadb + sentence-transformers)
brain-vector index rebuild
brain-vector search "<query>" --top-k 5
brain-vector status

# Webhook при завершении задачи
export BRAIN_WEBHOOK_URL=https://hooks.example.com/brain
export BRAIN_WEBHOOK_TIMEOUT_SEC=3     # default: 3
brain-task complete <id> --as <agent>  # → POST event к webhook

# Auto-next: watch + автопереход
brain-launch <task-id> --watch --auto-next         # live mode
brain-launch <task-id> --watch --auto-next --dry-run  # plan only
export BRAIN_WATCH_POLL_SEC=5          # default: 5
```

## Phase 5 — Learning Loop

```bash
# Capture incidents
brain-learn capture <task-id> --source human-edit --role developer --severity low --rule "..."
brain-learn capture --source smoke-failure --evidence "Test output here"
brain-learn amend <inc-id> --root-cause "..." --fix "..."

# List and inspect
brain-learn list                     # all non-rejected lessons
brain-learn list --pending           # pending only
brain-learn list --status active     # active only
brain-learn list incidents           # all incidents
brain-learn show <inc-id|les-id>

# Lifecycle
brain-learn approve <les-id> --as <agent>    # low/medium severity
brain-learn approve <les-id> --as arbiter-<suffix>  # high severity (arbiter required)
brain-learn activate <les-id>
brain-learn reject   <les-id> --as <agent>
brain-learn deprecate <les-id> --as <agent>

# Phase auto-capture (creates pending lessons, does NOT activate)
brain-learn phase-capture --phase phase5 --baseline-tag v4
```

## Phase 11 — Federation Plan

```bash
# Read-only plan from a repo/Brain pair
brain-federation plan --repo /path/to/repo --brain "$BRAIN_PATH" --json

# Explicitly write only the requested plan file
brain-federation plan --repo /path/to/repo --brain "$BRAIN_PATH" --out /tmp/brain-plan.json
```

`plan` embeds Phase 10 preflight findings and task import conflicts. Proposed
remote `[~]` tasks block import planning; local `[~]` tasks in the operator's
Brain are treated as local state, not imported-task conflicts.

## Env-переменные

| Переменная | Описание | Default |
|---|---|---|
| `BRAIN_PATH` | Путь к brain vault | `~/brain` |
| `BRAIN_WEBHOOK_URL` | URL для webhook событий | — (отключён) |
| `BRAIN_WEBHOOK_TIMEOUT_SEC` | Таймаут webhook (сек) | `3` |
| `BRAIN_WATCH_POLL_SEC` | Интервал опроса в watch-режиме (сек) | `5` |
| `BRAIN_REPO_DIR` | Путь к git-репо для phase-capture | `$PWD` |

Полный справочник CLI-агентов и примеры команд: [[cli-agents]].

Связанные страницы: [[workflow-solo-council]], [[decisions-log]].
