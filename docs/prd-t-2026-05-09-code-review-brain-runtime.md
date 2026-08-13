---
title: prd/t-2026-05-09-code-review-brain-runtime
type: project
created: 2026-05-09
updated: 2026-05-09
curation: agent
protected: false
source_policy: advisory
tags: [prd, code-review, refactoring]
sources: []
related: []
visibility: public
---

---
status: draft
task: t-2026-05-09-code-review-brain-runtime
created: 2026-05-09T08:01:08Z
---

# PRD: Code Review: устранить найденные проблемы в Brain Runtime

## Context

Проведено вертикальное и горизонтальное ревью кода Brain Runtime.
Найдены системные проблемы: DRY violations (6 копий parse_block), race condition в acquire_lock, самописный YAML-парсер, гибридная Bash/Python архитектура, отсутствие unit-тестов.
Полный текст ревью: handoff/2026-05-09-code-review.md

## Goals

1. Устранить дублирование парсинга задач — единый source of truth
2. Исправить race condition в acquire_lock Python-версии
3. Разбить brain_wiki.py на модули
4. Вынести Python-логику из Bash heredoc'ов в отдельные модули
5. Добавить TypedDict для core структур данных
6. Добавить unit-тесты для Python core (pytest)
7. Устранить security issues (sed injection, race condition)
8. Унифицировать error handling в MCP tools
9. Исправить асимметрию as_bool, as_list
10. Добавить валидацию webhook URL

## Non-goals

- Переписывание Bash-скриптов на Python
- Замена CI/CD
- Изменение формата active.md / done.md (обратная совместимость)
- Добавление новых фич (только рефакторинг)

## Subtasks

### 1. Единый парсер задач (task-parser)
- Создать `runtime/lib/brain_task_parser.py` — единый модуль с `parse_block()`, `find_block()`, `find_blocks()`, `is_done()`
- Заменить все inline-копии в `brain-task` heredoc'ах, `common.py`, `tools_orchestration.py`, `brain_tasks.py` на импорт из единого модуля
- Убрать дубликат `python3 - <<'PY'` с парсингом из brain-task

### 2. Refactoring brain_wiki.py (brain-wiki-split)
- Разбить `runtime/lib/brain_wiki.py` на модули:
  - `brain_wiki_frontmatter.py` — parse/format frontmatter, scalar helpers
  - `brain_wiki_validate.py` — validate_all, validate_wiki_page, validate_raw_source
  - `brain_wiki_uiux.py` — UI/UX routing, stale references
  - `brain_wiki_log.py` — лог, Obsidian-отчёт
- Заменить самописный YAML-парсер на `ruamel.yaml` или `PyYAML` (если zero-dep — покрыть тестами edge cases)
- Исправить `extract_wikilinks()` — split("#") после split("|")

### 3. Refactoring brain_index.py (brain-index-typed)
- Добавить TypedDict: `PageRecord`, `RawRecord`, `SearchDoc`, `Manifest`
- Объединить `search_doc_from_page` / `search_doc_from_raw` в одну функцию
- Разбить `rebuild_index()` на smaller функции
- Вынести `import brain_tasks` из тела `build_knowledge_graph()` наверх

### 4. Fix race condition в acquire_lock (lock-atomicity)
- Исправить `acquire_lock()` в `tools_orchestration.py`: использовать `mkdir`-атомарность как в `brain-lock` (bash)
- Добавить валидацию symlink в `shutil.rmtree()` для `.locks`

### 5. Extract Python from Bash heredocs (bash-py-extract)
- Вынести webhook-код из `brain-task` в `runtime/bin/brain-webhook-py.py` с CLI-интерфейсом
- Вынести Python-логику `show`, `next`, `list`, `deps` в отдельные Python-скрипты в `runtime/bin/`
- `brain-task` оставить как тонкий Bash-wrapper с вызовами Python-модулей

### 6. Unit tests for Python core (python-unit-tests)
- Добавить `pytest` + директорию `tests/unit/`
- Тесты для `brain_wiki_frontmatter.parse_frontmatter()` с edge cases
- Тесты для BM25 (`brain_index.BM25`)
- Тесты для `as_bool()`, `as_list()`, `normalize_slug()`
- Тесты для `acquire_lock()` с race condition
- Тесты для `parse_block()` из нового единого модуля

### 7. Error handling и consistency (error-handling)
- Единый формат ошибок MCP: `{"ok": false, "error": "code", "message": "..."}`
- Логирование ошибок `git_commit()` (сейчас тихо глотает)
- Исправить асимметрию `as_bool()`: добавить "n", "no", "0", "false"
- Исправить `validate_paths()`: добавить проверку `roles/`, `doctrine/`, `prd/`, `teams/`

### 8. Security fixes (security-hardening)
- Экранировать `$id` и `$reason` в `sed -i.bak` в brain-task block
- Добавить валидацию URL в webhook-доставке (allowlist или URL-parse check)
- Добавить `set -u` в brain-task (наряду с `set -e`)

### 9. Timestamp and naming consistency (consistency)
- Убрать дубликат `ts()`: выбрать одну функцию и использовать везде
- Унифицировать `import datetime as _dt` стиль во всех модулях
- Унифицировать конвертацию task state (char to string) в одном месте
