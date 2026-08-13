---
title: Brain reference
type: concept
created: 2026-08-11
updated: 2026-08-13
curation: agent
source_policy: advisory
tags: [brain, reference]
sources: []
related: []
visibility: public
---

# Brain reference

Справочные разделы, вынесенные из MEMORY.md: они не задают правил, а
описывают устройство. Цену их присутствия платил каждый запуск любого
агента — они шли в промпт целиком.

## Структура

```
~/brain/
├── MEMORY.md            ← этот файл (схема + конституция)
├── raw/                 ← источники, ИММУТАБЕЛЬНЫ
├── wiki/                ← знания
│   ├── index.md
│   └── log.md
├── tasks/
│   ├── active.md        ← очередь
│   ├── done.md
│   └── SCHEMA.md
├── roles/               ← локальный оверрайд ролей (необязательно)
├── council/             ← консилиум: одна задача — несколько мнений
│   └── <task-id>/
│       ├── <role>.md
│       └── synthesis.md
└── .locks/              ← блокировки задач (агентами)
    └── <task-id>/owner
```

Системные ассеты (`roles/`, `teams/`, `doctrine/`, `skills/`, `.cli-mapping.sh`)
живут в `$BRAIN_SYSTEM_PATH` (публичный чекаут). `$BRAIN_PATH` — слой данных.
Если `BRAIN_SYSTEM_PATH` не задан, оба слоя — в одном корне (legacy).

## Локальный оверрайд роли

Резолв файла системы: сначала `$BRAIN/<путь>`, затем `$BRAIN_SYSTEM_PATH/<путь>`.
Чтобы переопределить роль, не форкая систему, положи файл в data-корень:

```
$BRAIN_PATH/roles/developer.md
```

Он затеняет одноимённый файл из системного корня. Остальные роли по-прежнему
берутся из `$BRAIN_SYSTEM_PATH/roles/`. То же правило для `teams/`, `doctrine/`,
`skills/` и `.cli-mapping.sh`.

`brain-status` печатает оба пути (`Brain:` и `System:`).

После переезда ADR в `docs/decisions/` и концептуальных страниц в `docs/`
`brain-validate`, `brain-index` и `brain-search` смотрят оба корня: слаги
системных страниц резолвятся, кросс-корневые вики-ссылки не считаются
битыми. Если при двух корнях в приватном дереве снова появляются `runtime/`,
`tests/`, `spec/` или `docs/`, валидатор отвечает ошибкой «системный путь
восстановлен в приватном дереве». Локальный оверрайд `roles/` этой проверке
не подпадает. Раскладка «один корень» (без `BRAIN_SYSTEM_PATH`) не меняется.

## CLI-инструменты (Wiki-стек)

- `brain-ingest [file|-] --slug <slug>` — загрузка Markdown/text источника в `raw/` с метаданными.
- `brain-validate` — проверка целостности wiki и контрактов курации.
- `brain-lint` — поиск логических ошибок, дублей и orphan-страниц.
- `brain-index rebuild` — пересборка `.brain/index/` machine cache (pages/links/sources/search).
- `brain-search "<query>"` — BM25-поиск по machine cache; если индекс stale, сначала `brain-index rebuild`.

## Optional Obsidian Skills

Если установлены `kepano/obsidian-skills`, используй их для форматов Obsidian:
`obsidian-markdown` для `wiki/*.md`, `obsidian-bases` для `.base`,
`json-canvas` для `.canvas`, `obsidian-cli` для открытого vault и `defuddle`
для очистки web-страниц перед `brain-ingest`. Эти skills не меняют приоритет
курации: `curation: human` и `protected: true` остаются неперезаписываемыми.

