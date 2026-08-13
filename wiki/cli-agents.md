---
title: CLI Agents — Таблица и примеры команд
type: concept
created: 2026-05-03
updated: 2026-05-03
curation: agent
protected: false
source_policy: advisory
tags: [cli, agents, workflow, reference]
sources: []
related: [decision-llm-stack, workflow-solo-council, roles-overview, model-fleet-report]
visibility: public
---

# CLI Agents — справочник для Brain

Справочник CLI-агентов, совместимых с Brain. Каждый агент подключается через
`brain-link` (создаёт симлинки CLAUDE.md / AGENTS.md / GEMINI.md → ~/brain/MEMORY.md)
или через MCP (`brain-mcp`).

Сводка эффективности моделей поддерживается в [[model-fleet-report]].

---

## Сравнительная таблица

| Агент         | Провайдер  | Команда запуска         | Подключение к Brain       | Рекомендованные роли Brain |
|---------------|------------|-------------------------|---------------------------|---------------------------|
| Claude Code   | Anthropic  | `claude`                | CLAUDE.md симлинк + MCP   | architect, developer, arbiter |
| Codex CLI     | OpenAI     | `codex`                 | AGENTS.md симлинк         | reviewer, developer       |
| Gemini CLI    | Google     | `gemini`                | GEMINI.md симлинк         | researcher, reviewer      |
| Cursor        | Anthropic/OpenAI | (IDE)             | CLAUDE.md / .cursorrules  | developer, linter         |
| OpenCode      | OpenAI     | `opencode`              | AGENTS.md симлинк         | developer                 |
| Aider         | Multi      | `aider`                 | AGENTS.md / .aider.conf   | developer                 |
| Continue      | Multi      | (IDE extension)         | через MCP                 | developer, linter         |

---

## Рабочие примеры команд

### Claude Code

```bash
# Подключить Brain к проекту (создаёт CLAUDE.md симлинк)
cd ~/my-project && brain-link

# Запустить задачу в роли developer
brain-run --role developer --task t-2026-05-01-foo --agent-id dev-1 | claude

# Запустить arbiter после совета
brain-run --role arbiter --task t-foo --council | claude

# MCP-режим (агент имеет доступ к 42 brain-инструментам)
claude mcp add brain "$HOME/.local/bin/brain-mcp"
claude  # теперь /brain/* инструменты доступны в сессии
```

### Codex CLI

```bash
# Подключить Brain (AGENTS.md)
cd ~/my-project && brain-link

# Запустить reviewer
brain-run --role reviewer --task t-foo --agent-id rev-1 | codex

# MCP-режим (если Codex поддерживает)
# codex --mcp-server "$HOME/.local/bin/brain-mcp"
```

### Gemini CLI

```bash
# Подключить Brain (GEMINI.md симлинк)
cd ~/my-project && brain-link

# Запустить researcher
brain-run --role researcher --task t-foo --agent-id res-1 | gemini

# Совет: Gemini хорошо справляется с большими контекстами (1M токенов)
# Использовать для задач с большим объёмом wiki/raw материала
```

### Параллельная работа двух агентов

```bash
# Терминал 1: developer на Claude
DEV="dev-$(head -c4 /dev/urandom | xxd -p)"
brain-task take t-foo --as $DEV
brain-run --role developer --task t-foo --agent-id $DEV | claude
brain-task complete t-foo --as $DEV

# Терминал 2: reviewer на Codex (параллельно)
REV="rev-$(head -c4 /dev/urandom | xxd -p)"
brain-task take t-bar --as $REV
brain-run --role reviewer --task t-bar --agent-id $REV | codex
brain-task complete t-bar --as $REV
```

### Council в tmux (brain-launch)

```bash
# Создать council-задачу
brain-task add "Выбрать архитектуру БД" --role architect --mode council --prio P1
# Добавить council в active.md: council: [architect, reviewer, researcher]
TID="t-2026-05-03-<slug>"

# Запустить tmux с 3 окнами (по одному на роль)
brain-launch $TID

# Посмотреть план без запуска
brain-launch $TID --dry-run

# Мониторинг сессии
brain-launch $TID --watch --dry-run

# После завершения: синтез
brain-council synthesize $TID
brain-run --role arbiter --task $TID --council | claude
```

---

## Brain shell (интерактивный режим)

```bash
# Запустить интерактивный шелл
brain-shell

# Команды внутри:
# status          — сводка оркестрации
# tasks           — список активных задач
# tasks developer — задачи для роли developer
# next developer  — следующая доступная задача
# locks           — активные блокировки
# search <query>  — поиск по wiki
# dashboard export — сгенерировать HTML дашборд
# take <id> --as <agent>     — взять задачу
# release <id> --as <agent>  — отпустить задачу
# complete <id> --as <agent> — завершить задачу
# quit

# One-shot режим (для скриптов)
brain-shell --once status
brain-shell --once "tasks developer"
brain-shell --once "search api design"
```

---

## Подключение MCP к Claude Code

```bash
# 1. Установить MCP-сервер
bash install-brain-mcp.sh

# 2. Зарегистрировать в Claude Code
claude mcp add brain "$HOME/.local/bin/brain-mcp"

# 3. Проверить доступные инструменты
claude  # в сессии: /brain или через tool-use

# MCP инструменты (42 шт.):
# list_tasks, get_task, add_task
# take_task, release_task, complete_task
# search_brain, read_wiki_page, write_wiki_page
# rebuild_index, dashboard_status, dashboard_export
# list_doctrines, get_doctrine, search_doctrines
# init_prd, commit_prd, get_prd_status
# ... и др.

# HTTP-режим MCP (для удалённых агентов)
brain-mcp --http --port 8766
# Агенты подключаются через SSE: http://127.0.0.1:8766
```

---

## Шпаргалка brain-task

```bash
brain-task                         # показать active.md
brain-task next                    # следующая доступная задача
brain-task next --role developer   # для конкретной роли
brain-task show <id>               # детали задачи
brain-task add "Описание" --role R --prio P1
brain-task take <id> --as <agent>
brain-task complete <id> --as <agent>
brain-task release <id> --as <agent>
brain-task block <id> "причина"
brain-task log 20                  # последние 20 событий
```

---

## Диагностика и обслуживание

```bash
brain-status                  # текстовый статус системы
brain-status --json           # JSON для скриптов
brain-validate                # проверка wiki-контрактов
brain-lint --fix-index        # исправить индекс и ссылки
brain-index rebuild           # пересобрать поисковый индекс
brain-index rebuild --with-obsidian  # + Obsidian-вьюхи
brain-search "запрос"         # BM25-поиск по wiki
brain-lock status             # все активные локи
brain-lock cleanup            # удалить stale локи
brain-dashboard export        # статический HTML-дашборд
brain-dashboard serve         # живой дашборд на :8765
```
