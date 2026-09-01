# brain — Contract (stable ABI)

> Stable contract surface: file layout, task format, lock/council/PRD protocols,
> wiki contract, indexing format, policy profiles, and version table.
> Living guide: see [./guide.md](./guide.md). Top-level entry: [../brain-spec.md](../brain-spec.md).

## Структура файлов

```
~/brain/
├── MEMORY.md                  # Schema + escalation matrix. Читается
│                              # каждым агентом перед работой.
│
├── roles/                     # Персоны для агентов
│   ├── architect.md
│   ├── developer.md
│   ├── reviewer.md
│   ├── security.md
│   ├── researcher.md
│   ├── linter.md
│   ├── arbiter.md
│   ├── lawyer.md
│   ├── compliance.md
│   ├── paralegal.md
│   ├── strategist.md
│   ├── copywriter.md
│   ├── designer.md
│   ├── growth-analyst.md
│   ├── pm.md
│   ├── product.md
│   ├── delivery.md
│   ├── cfo.md
│   ├── accountant.md
│   ├── tax-advisor.md
│   ├── qa.md
│   ├── sre.md
│   ├── tech-writer.md
│   └── negotiator.md
│
├── teams/                     # Алиасы для совета
│   ├── engineering.md         # architect + developer + reviewer
│   ├── legal.md               # lawyer + compliance + paralegal
│   ├── marketing.md           # strategist + copywriter + growth-analyst
│   ├── creative.md            # designer + copywriter + strategist
│   ├── pm.md                  # pm + product + delivery
│   ├── finance.md             # cfo + accountant + tax-advisor
│   ├── negotiation.md         # negotiator + lawyer + cfo
│   ├── operations.md          # sre + qa + tech-writer
│   └── research.md            # researcher + growth-analyst + reviewer
│
├── doctrine/                  # Разграничения на стыках ролей
│   ├── tax-boundaries.md      # 4-этапная модель налоговой работы
│   └── legal-vs-compliance.md # разовый документ vs регулярный процесс
│
├── tasks/
│   ├── active.md              # Очередь открытых задач
│   ├── done.md                # Завершённые (свежие сверху)
│   └── SCHEMA.md              # Формат задачи
│
├── prd/                       # PRD-документы
│   ├── _TEMPLATE.md
│   └── <task-id>.md           # Один файл на PRD-задачу
│
├── council/
│   └── <task-id>/
│       ├── <role>.md          # Мнение каждой роли
│       └── synthesis.md       # Синтез arbiter'a
│
├── wiki/
│   ├── index.md               # Каталог страниц
│   ├── log.md                 # Append-only журнал операций
│   └── <slug>.md              # Страницы знаний (с frontmatter)
│
├── raw/                       # Источники (immutable)
│   └── <slug>.md              # Статьи, PDF-выгрузки, транскрипты
│
├── skills/
│   └── uiux/
│       ├── core/              # generic UI/UX workflow skills
│       ├── brain/             # Brain dashboard/orchestration skills
│       └── handoff/           # developer/copywriter handoff skills
│
├── .locks/                    # Эфемерные блокировки
│   └── <task-id>/owner        # owner|epoch_ts|ttl
│
├── .agent-configs/            # Симлинки для разных CLI
│   ├── CLAUDE.md → ../MEMORY.md
│   ├── AGENTS.md → ../MEMORY.md
│   ├── GEMINI.md → ../MEMORY.md
│   └── .cursorrules → ../MEMORY.md
│
├── .cli-mapping.sh            # Маппинг роль → CLI команда
│                              # (для brain-launch; в .gitignore)
│
├── handoff/
│   └── ORCHESTRATOR_HANDOFF.md # Последний handoff при quota/context-limit
│
├── .gitignore
└── .git/                      # Локальный репозиторий
```

Глобально симлинки:
```
~/.claude/CLAUDE.md → ~/brain/MEMORY.md
~/.codex/AGENTS.md  → ~/brain/MEMORY.md
~/.gemini/GEMINI.md → ~/brain/MEMORY.md
```

CLI в PATH:
```
~/.local/bin/brain-task
~/.local/bin/brain-lock
~/.local/bin/brain-council
~/.local/bin/brain-prd
~/.local/bin/brain-launch
~/.local/bin/brain-handoff
~/.local/bin/brain-orchestrator
~/.local/bin/brain-provider
~/.local/bin/brain-federation
~/.local/bin/brain-run
~/.local/bin/brain-link
~/.local/bin/brain-mcp
```

MCP-сервер:
```
~/.local/share/brain-mcp/
├── .venv/                     # Python venv с fastmcp
└── server.py                  # FastMCP server, 42 tool
```

---


## Реестр команд

8 team-файлов. Каждый разворачивается в список ролей при старте совета.

| Team | Роли | Использование |
|---|---|---|
| `engineering` | architect + developer + reviewer | архитектурные развилки, безопасность |
| `legal` | lawyer + compliance + paralegal | ревью договоров, регуляторка, контрагенты |
| `marketing` | strategist + copywriter + growth-analyst | запуски, кампании, контент-стратегия |
| `creative` | designer + copywriter + strategist | брендинг, лендинги, презентации |
| `pm` | pm + product + delivery | приоритизация, ретро, планирование |
| `finance` | cfo + accountant + tax-advisor | юр.форма, инвест.решения, режим налогообложения |
| `negotiation` | negotiator + lawyer + cfo | подготовка к крупным сделкам |
| `research` | researcher + growth-analyst + reviewer | due-diligence, deep-dive |
| `operations` | sre + qa + tech-writer | поддержка здоровья системы, тесты, Wiki |

Использование в задаче:
```
council: [team:legal]                    # 3 роли
council: [team:legal, growth-analyst]    # 4 роли (3 + 1)
council: [team:finance, lawyer]          # 4 роли с пересечением (lawyer не дублируется)
council: [product, cfo, lawyer]          # без team — явный список
```

Дедупликация выполняется при разворачивании.

## UI/UX Skill Pack

Canonical path:

```text
skills/uiux/{core,brain,handoff}/<slug>.md
```

Each skill file has YAML frontmatter with `name`, `version`, `status`,
`owner_role`, `group`, `applies_to`, `invoked_by`, `consumed_by`, `trigger`,
`requires`, `forbidden_zones`, `output_format`, `max_lines`.

`applies_to` is a multi-role usage gate. UI/UX skills must include `designer`,
but may also include `product`, `developer`, `reviewer`, `copywriter`, or other
roles when the skill directly supports that role's workflow. Use `owner_role`
for accountability, `invoked_by` for normal callers, and `consumed_by` for
roles expected to act on the output.

Canonical UI/UX council:

```text
[product, designer, developer, reviewer]
```

Role boundaries:

- `designer`: UI/UX intent and constraints.
- `product`: JTBD, scope, success metrics.
- `developer`: implementation details.
- `copywriter`: final microcopy.
- `reviewer`: quality review.
- `linter`: skill-pack hygiene.

---


## Формат задач

`tasks/active.md` содержит блоки:

```
- [ ] [P1] t-2026-05-01-example — Короткое название
      role: developer    mode: solo
      depends_on: [t-prev-1, t-prev-2]
      due: 2026-05-15    tags: #area
      Контекст в одно-два предложения.
      acceptance: что должно работать в конце.
      ref: [[wiki/page]] | raw/file.md
```

### Состояния

| Маркер | Состояние | Семантика |
|---|---|---|
| `[ ]` | open | можно брать |
| `[~]` | in-progress | взято агентом, обязательно лок |
| `[x]` | done | завершено, переносится в done.md |
| `[!]` | blocked | заблокировано, причина в комментарии |

### Поля

| Поле | Обязательно | Описание |
|---|---|---|
| `[Px]` | да | Приоритет: P0 (срочно) / P1 (важно) / P2 (когда руки) |
| `t-YYYY-MM-DD-<slug>` | да | Уникальный id |
| `role:` | нет (default `developer`) | Какая роль исполняет |
| `mode:` | нет (default `solo`) | `solo` / `council` / `prd` |
| `council:` | для `mode: council` | Список ролей или team-алиасов |
| `depends_on:` | нет | Список id, которые должны быть `[x]` до старта |
| `due:` | нет | Срок |
| `tags:` | нет | Теги для группировки |
| `acceptance:` | да | Критерий готовности |
| `ref:` | нет | Wikilinks или raw/file.md |
| `parent:` | для PRD-сабтасков | Id родительской PRD-задачи |

### Машинные поля (добавляются автоматически)

```
      started: 2026-05-01T10:30:00Z
      by: claude-opus-7f3a
      completed: 2026-05-01T15:42:00Z
      summary: краткое описание сделанного
```

### ID convention

```
t-YYYY-MM-DD-<slug>                   # обычная задача
<parent-id>-s1                        # PRD сабтаск (s1, s2, ...)
```

### Identifier contract (security)

Все идентификаторы, передаваемые в CLI-инструменты (task-id, role, session),
должны соответствовать строгим regex-паттернам. Это предотвращает shell-injection
через tmux, awk и другие интерпретаторы.

| Идентификатор | Regex | Где валидируется |
|---|---|---|
| task-id | `^[a-z0-9._-]+$` | brain-launch (entry point) |
| role | `^[a-z0-9_-]+$` | brain-launch (после чтения council:) |
| session | `^[a-z0-9._-]+$` | brain-launch (вход + после генерации) |

Несоответствующие идентификаторы завершаются с exit 1 и явным сообщением:
`brain-launch: invalid <type> '<value>' — must match ^<regex>$`.

---


## Lock protocol

Атомарная блокировка через `mkdir` (POSIX-гарантия атомарности).

### Структура

```
~/brain/.locks/<task-id>/owner       # содержимое: <agent-id>|<epoch_ts>|<ttl_seconds>
```

### Операции

```bash
brain-lock acquire <id> --as <agent> [--ttl 3600]
# → "ok" | "locked by: <agent> (age Xs, ttl Yms)"
# Если TTL истёк → автоматически перехватывает stale lock.
# Владелец может complete/release после expiry, пока лок ещё его.

brain-lock release <id> [--as <agent>]
# Если --as передан, проверяется владение.

brain-lock refresh <id> --as <agent> [--ttl 3600]
# Только владелец может продлить.

brain-lock status [<id>]
brain-lock cleanup
# Удаляет все stale-локи (TTL истёк).
```

### Правила для агентов

1. **Перед** изменением статуса `[ ]` → `[~]` агент **обязан** запросить лок.
2. Если задача занята другим — выбирает следующую, **не ждёт**.
3. По завершении — release. По отказу — тоже release.
4. Длинная задача (>10 мин) — периодически refresh.
5. Если упал — лок становится stale через TTL и перехватывается.
6. Действующий лок закрывает задачу и в состоянии `[ ]`: `brain-task complete`
   (и его recovery по журналу) требует владельца лока, даже если `take` ещё не
   выполнен и поля `by:` нет. Иначе окно между `acquire` и `take` оставалось бы
   дырой, через которую задачу закрывает посторонний агент. Протухший,
   нечитаемый и отсутствующий лок задачу не держат — по тому же правилу, по
   которому их перехватывает `acquire`.

### Что не покрыто локами

- **wiki/log.md** — append-only, race-condition не страшен (могут
  склеиться строки, но никто не теряется).
- **wiki/<page>.md** — теоретически возможна гонка двух обновлений.
  На практике решается культурой: по одной странице обычно правит одна
  роль (linter поддерживает индекс, researcher — source-summaries).
- **active.md** — критичный файл. При параллельной работе всё-таки
  есть риск гонки на больших правках. Рекомендация: серьёзные правки
  делать через atomic-rename pattern (write to .tmp, rename).

---


## Council protocol

Режим, когда несколько ролей дают независимые мнения, потом arbiter
синтезирует.

### Запуск

```bash
brain-council start <task-id>
```

Действия:
1. Читает `council:` из задачи в active.md.
2. Разворачивает `team:<name>` в полные роли.
3. Создаёт `~/brain/council/<id>/` с одним skeleton-файлом на роль.
4. Печатает команды для запуска каждой роли.

### Skeleton мнения

```yaml
---
task: <id>
role: <role>
agent: TODO
model: TODO
written: TODO
---

## Position
## Reasoning
## Risks / Open questions
## Recommendation
```

### Правила

1. Каждая роль пишет **независимо**. Не читай ответы коллег до завершения
   своего — это снижает корреляцию мнений.
2. После записи `written: <ts>` (не TODO) считается готовым.
3. Когда все роли отписались, можно вызывать synthesize.

### Синтез

```bash
brain-council synthesize <task-id>
# Создаёт skeleton synthesis.md.
# Затем arbiter заполняет его (через brain-run или MCP).
```

Структура synthesis.md:
```yaml
---
task: <id>
synthesized: <ts>
arbiter: <agent-id>
inputs: [architect.md, reviewer.md, researcher.md]
---

## Positions (TL;DR)        # одна строка на роль
## Agreement                 # где сходятся
## Disagreement              # где расходятся, и в чём корень
## Decision                  # что делать
## Why                       # обоснование выбора
## Open questions            # что осталось неясным
## Follow-up tasks           # новые задачи, если синтез предполагает действия
```

### Принципы для arbiter

- Не самый громкий — самый правый.
- Не средневзвешенное.
- Явно говори «не знаю» если данных нет — заводи researcher-задачу.

### Guardrails — проверка готовности

```bash
brain-council check <task-id>
```

Машинопроверяемый checklist (без LLM):

| Проверка | Уровень |
|----------|---------|
| `agent:` не TODO у всех ролей | ERROR |
| `written:` не TODO у всех ролей | ERROR |
| `## Position` непустая | ERROR |
| `## Recommendation` непустая | ERROR |
| `synthesis.md` существует и не skeleton | WARN |
| Все роли — один agent ID (solo council) | WARN |

**Solo council** (один агент пишет все роли) — допустимый паттерн, не ошибка.
`check` выдаёт WARN, не FAIL. Документируй в логе совета.

Полный checklist и примеры: [[wiki/council-guardrails]].

---


## PRD-режим

Декомпозиция крупной работы на сабтаски с зависимостями.

### Workflow

```bash
# 1. Создать parent-задачу с mode: prd
brain-task add "Внедрить фичу X" --role architect --mode prd

# 2. Создать PRD-документ по шаблону
brain-prd init <parent-id>
# → ~/brain/prd/<parent-id>.md

# 3. Архитектор заполняет PRD, особенно секцию ## Subtasks:
#    - [ ] [P1] s1 — Спроектировать схему БД
#          role: architect
#          depends_on: []
#          acceptance: ADR в wiki/...
#    - [ ] [P1] s2 — Реализовать API
#          role: developer
#          depends_on: [s1]
#          acceptance: ...
#    - [ ] [P1] s3 — Реализовать UI
#          role: developer
#          depends_on: [s1]
#    - [ ] [P2] s4 — Документация
#          role: researcher
#          depends_on: [s2, s3]

# 4. Зафиксировать сабтаски в active.md
brain-prd commit <parent-id>
# → 4 subtasks committed: <parent>-s1, <parent>-s2, <parent>-s3, <parent>-s4
# Локальные s1, s2, ... разворачиваются в полные id.
# depends_on: [s1] переписывается в depends_on: [<parent>-s1].
# Каждому сабтаску добавляется parent: <parent-id>.

# 5. Развильчивание по deps работает автоматически
brain-task next --role developer
# → пока s1 не done, отдаст: "(no available — заблокированы)"
# После complete s1 → отдаст s2 или s3.

# 6. Прогресс
brain-prd status <parent-id>
brain-task deps <subtask-id>          # граф зависимостей с маркерами
```

### Семантика

- `parent:` — указывает на PRD-задачу.
- `depends_on:` — задача доступна только когда все указанные deps `[x]`.
- `brain-task next` учитывает deps: возвращает первую available задачу.
- При запросе с фильтром по роли — учитывает оба условия (роль + deps).
- Граф зависимостей — DAG. Циклы не запрещены технически, но логически
  не имеют смысла (создадут дедлок).

---


## Wiki

### Структура страницы

```yaml
---
title: ...
type: concept | entity | project | source-summary | decision
tags: [...]
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: [raw/foo.md, raw/bar.pdf]
related: [[other-page]]
---

# Содержание...
```

### Типы

| `type:` | Назначение |
|---|---|
| `concept` | Общее понятие/термин |
| `entity` | Конкретная сущность (компания, человек, продукт) |
| `project` | Внутренний проект |
| `source-summary` | Саммари одного источника из `raw/` |
| `decision` | ADR-style: что и почему решили |

### Wiki & Curation Contract

1. **Приоритет курации:** Ручные (человеческие) правки имеют абсолютный ПРИОРИТЕТ над данными из источников.
   - Поля `protected: true` или `curation: human` блокируют автоматическую перезапись.
   - Агенты должны предлагать изменения (proposals), а не применять их молча.
2. **Источники (raw/):** ИММУТАБЕЛЬНЫ. Это улики и советы (evidence/advisory).
   - Используются для генерации `source-summary`.
   - На базе источников формируются задачи на обновление wiki.
3. **Политика (source_policy):** Поле в wiki-странице, определяющее режим обновления:
   - `advisory`: источники советуют, но не перезаписывают ручную курацию.
   - `required`: страница обязана иметь валидные `sources`.
   - `ignored`: источники не применяются к странице.

### `wiki/index.md`

Каталог всех страниц по группам (Concepts / Entities / Projects /
Decisions / Sources). Поддерживается ролью `linter`.

### `wiki/log.md`

Append-only журнал. Формат:

```
## [YYYY-MM-DDTHH:MM:SSZ] <op> | <id> | <agent-id> | <one-line>

ops:
  ingest          # добавлен источник в raw/
  task-add        # добавлена задача
  task-start      # взята в работу (-)
  task-done       # завершена
  task-release    # возвращена в open
  task-block      # помечена blocked
  lock-acquire
  lock-release
  council-start
  council-opinion
  council-synth
  prd-init
  prd-commit
  wiki-update
  lint
```

### Wikilinks

`[[<page-slug>]]` — ссылка на другую страницу. Совместимо с Obsidian.

### Lint & Validate

Линтер и валидатор (`brain-lint`, `brain-validate`) проверяют:
- нарушения Wiki Contract (авто-правки в protected-зонах);
- orphan-страницы (без inbound links);
- упомянутые но не созданные `[[concept]]`;
- дубли (две страницы про одно);
- стейл (`updated:` старше 6 мес.);
- broken refs в задачах;
- stale locks.

---


## Indexing — поисковый движок и метаданные

Система использует легковесный поисковый движок на базе BM25 и JSON-индекса,
генерируемого из Markdown-файлов. Индекс хранится в `.brain/index/` под
`BRAIN_PATH` и считается кешем (исключён из git).

### Компоненты индекса

| Файл | Описание |
|---|---|
| `pages.json` | Список wiki-страниц: slug, path, title, type, curation, sources, links |
| `links.json` | Граф wikilinks: nodes, edges, backlinks, missing targets |
| `sources.json` | Карта wiki ↔ raw: raw_to_pages, source_summaries, missing_sources |
| `search.jsonl` | Текстовые документы для BM25: wiki, raw и task docs |
| `manifest.json` | Метаданные: дата rebuild, counts, mtimes source-файлов |

### Поисковый алгоритм (BM25)

Для ранжирования результатов используется классический алгоритм BM25,
реализованный на чистом Python без внешних зависимостей. Это обеспечивает:
- Учёт частоты терминов (TF).
- Обратную частоту документов (IDF) — редкие слова весят больше.
- Нормализацию длины документов — длинные тексты не имеют несправедливого
  преимущества.

### Backlinks

Благодаря `links.json`, система предоставляет инструмент получения обратных
ссылок (кто ссылается на данную страницу). Это критично для понимания
контекста и связности знаний.

### Freshness

`.brain/index/` не коммитится и пересобирается командой `brain-index rebuild`.
`brain-index stale` сравнивает mtimes `wiki/*.md`, `raw/*.md`, `tasks/*.md`
с `manifest.json`. Generated-файлы `wiki/index.md`, `wiki/log.md` и
`wiki/_views/*` не делают machine index stale.

---


## Векторный поиск (опциональный слой)

Поверх BM25 доступен опциональный векторный поиск через `brain-vector`.
Он **не заменяет** `brain-search` (BM25), а дополняет его.

### Контракт optional-зависимости

Векторный слой требует `chromadb` и `sentence-transformers`. Если они
недоступны, `brain-vector` завершается с кодом 1 и понятным сообщением:

```
brain-vector: dependency missing — install chromadb and sentence-transformers:
  pip install chromadb sentence-transformers
Fallback: use brain-search (BM25) instead.
```

Это поведение требуется для любой операции (`index`, `search`, `status`).

### Хранилище вектора

Индекс хранится в `$BRAIN_PATH/.brain/vector/` (рядом с `.brain/index/`).
Исключён из git (`.gitignore`). Не влияет на BM25-индекс.

### Fallback flow

```
brain-vector search "<q>"
  → chromadb доступен? → векторный поиск → ranked results
  → нет              → exit 1 + "use brain-search"
```

`brain-search` (BM25) всегда работает независимо от vector-слоя.

### Support matrix

`brain-vector support [--json]` — read-only contract command. It reports:

- primary backend: ChromaDB + `sentence-transformers`, optional;
- embedding model: `all-MiniLM-L6-v2`;
- fallback backend: BM25 via `brain-index` / `brain-search`, required;
- decision: ChromaDB stays optional, BM25 remains the dependency-light baseline.

### Error paths

| Сценарий | Поведение |
|---|---|
| `chromadb` не установлен | exit 1, сообщение + `pip install` |
| вектор-индекс не собран | exit 1, сообщение + `brain-vector index rebuild` |
| BRAIN_PATH не существует | exit 1, стандартная ошибка brain-common |
| embedding-модель недоступна | exit 1, точное сообщение из sentence-transformers |

---


## Policy Profiles (Phase 6)

### Зачем нужны policy profiles

Каждый CLI-провайдер (`claude`, `codex`, `gemini`) применяет собственные
политики безопасности, которые могут блокировать Brain-операции:

- запись файлов в `~/brain/`
- исполнение shell-команд (`run_shell_command`, bash tools)
- чтение системных конфигов (`~/.claude/`, `~/.codex/`)
- сетевые запросы (webhook delivery)

**Policy profile** — набор разрешений и scope, необходимый Brain-агенту для
корректной работы в конкретном провайдере.

### Policy contract по провайдерам

| Провайдер | Необходимые разрешения | Известные ограничения |
|---|---|---|
| **claude** (Claude Code) | `bash`, `read`, `write`, `edit` | `--dangerously-skip-permissions` для неинтерактивного режима |
| **codex** | `run_shell_command` (в AGENTS.md scope) | Sandbox: ограниченная запись за пределами `/tmp` и проекта |
| **gemini** (Gemini CLI) | `shell` tool в GEMINI.md | Не поддерживает MCP напрямую; работает через `brain-run | gemini` |

### Разрешённый scope `run_shell_command` для Brain

Следующие операции **должны быть разрешены** для корректной работы Brain:

```
brain-lock acquire/release/refresh
brain-task take/complete/next
brain-run --role <role> --task <id>
brain-lint / brain-validate / brain-status
brain-learn capture/list/show/approve/activate/quality-check/prune-expired
brain-task webhook-replay
brain-policy check
brain-release check / brain-release tag <vN>
brain-index rebuild
```

Следующие операции **не требуются** для стандартного workflow (scope ограничен):

```
git push  — выполняется агентом явно, не как часть workflow
rm -rf    — никогда не нужен в Brain runtime
curl      — только через brain-task webhook (внутри скрипта)
```

### Policy Denied: troubleshooting

**Признак:** Провайдер отклоняет `run_shell_command` / bash tool с ошибкой
`policy denied` или `tool not allowed`.

**Диагностика:**
```bash
brain-policy check              # (новая команда Phase 6)
# Выводит: provider, allowed tools, scope, any blocked ops
```

**Для claude:**
```bash
# Non-interactive run (CI/automation):
claude --dangerously-skip-permissions -p "$(brain-run --role developer --task <id>)"
# В сессии: одобри инструменты bash/write/read при первом запросе
```

**Для codex:**
```bash
# Убедись, что ~/.codex/AGENTS.md (→ ~/brain/MEMORY.md) содержит:
# run_shell_command: allow
# working_directory: не ограничена или включает ~/brain/
```

**Для gemini:**
```bash
# Gemini CLI читает GEMINI.md; Brain работает через pipe:
brain-run --role developer --task <id> | gemini
# Прямых shell-вызовов из gemini нет — только вывод brain-run читается gemini
```

**Fallback при policy deny:**
1. Выполни заблокированную команду вручную в терминале.
2. Запиши результат как incident: `brain-learn capture --source runtime-error --evidence "policy denied: <op>"`.
3. После исправления policy — продолжи.

### Policy Readiness Check

Запускается как частью `brain-policy check` или smoke-тестами:

1. `brain-status` доступна (read `~/brain/`)
2. `brain-lock acquire` + `release` без ошибок (write `.locks/`)
3. `brain-task take` + `complete` без ошибок (write `tasks/`)
4. `brain-learn capture` создаёт файл в `~/brain/learning/`
5. `brain-run --role developer` возвращает непустой stdout

Если хотя бы один пункт провален — Brain workflow заблокирован; смотри
troubleshooting выше.

---


## Agent-tool handoff convention (Phase 17)

Когда Claude Code Agent tool (или другой внутрипроцессный subagent) упирается в
лимит токенов или квоту (сообщение вида `You've hit your limit`, `rate_limit_error`, и т.д.),
он не падает с системным кодом ошибки, а возвращает `status: completed` с текстом
ошибки внутри `result`. Main session должна:

1. Перехватить этот `task-notification` (JSON или Markdown dump).
2. Вызвать `brain-handoff create --from-task-output <file>` или 
   `brain-handoff auto-from-clipboard`.
3. Это автоматически извлечёт `task-id`, `agent-id`, `reason` и создаст
   handoff артефакт, записав лог `orchestrator-handoff` в `wiki/log.md`.

---


## Версионирование

Версия системы определяется наличием addon'ов:

| Версия | Что добавлено |
|---|---|
| v1.0 | базовая память, симлинки на конфиги CLI |
| v2.0 | роли, локи, совет, brain-run, brain-task с локами |
| v2.1 | + legal + marketing команды |
| v2.2 | + pm + finance команды |
| v2.3 | + designer + negotiator + escalation matrix |
| v2.4 | + doctrine + tax-boundaries + автоподгрузка doctrine |
| v2.5 | + PRD-режим + tmux-launcher + git auto-commit |
| v2.6 | + MCP-сервер (42 tool) |
| v2.7 | + dashboard SSE live-refresh + audit log + POST actions (take/release/complete) |
| v2.8 | + brain-shell --yes + brain-council check + obsidian sync-report |
| v3.0 | + MCP HTTP hardening + E2E drill + ops runbook с верифицированными сценариями |
| v4.0 | + brain-vector (optional ChromaDB) + webhook task-done + brain-launch --auto-next |
| v5.0 | + brain-learn CLI + learning loop (capture/approve/activate/inject) + phase-capture |
| v6.0 | + brain-policy check + brain-release (check/tag) + webhook retry/dead-letter + learning quality controls + /api/metrics |
| v7.0 | + shell injection guards (brain-launch) + identifier contract |
| v8.0 | + dark dashboard/task board + token economy + provider matrix + orchestrator handoff on limit |
| v9.0 | + provider health refresh CLI + dashboard write auth token + task filters/grouping + handoff JSON + federation design contract |
| v10.0 | + read-only brain-federation preflight + task conflict reporter + dashboard read auth |
| v11.0 | + federation plan/import/proposal writers + dashboard token URL cleanup + optional local secret scanner + security role |
| v12.0 | + UI/UX skill pack (12 active + 2 draft skills) + designer role sync + handoff/benchmark updates |
| v20.0 | + Universal Skill Architecture (YAML), JIT Config Injection, brain-skill CLI, Graceful Client Degradation |
| v21.0 | + Opencode and Kilocode JIT support |
| v22.0 | + Autonomous Skill Curator (brain-curator monitor/search/synthesize/rank-models/monitor-limits) |
| v23.0 | + Federation Merge Workflow (brain-federation sync, 3-way task merge, federated lock conflicts) |
| v23.1 | + Skill-aware routing/fallback fixes and release diagnostics hardening baseline |
| v24.0 | + Operator Console / Visual Orchestration (`brain-orchestrator console`, visible logs, dashboard operator panel, visual regression checks) |
| v25.0 | + Automation & QoL (`brain-ops`, launch-watch ops refresh, council run automation, `brain-prd auto-breakdown`, local CI/pre-commit scaffolding) |
| v25.1 | + Consolidated live Brain repository layout and generated artifact/history hygiene |

Текущая версия определяется по наличию `~/brain/doctrine/`,
`~/brain/prd/`, `brain-mcp`, `brain-council check`, `brain-vector`,
`brain-learn`, `brain-release`, `brain-compact`, `brain-compact-adapters`,
`brain-handoff`, `brain-provider`, `brain-federation`, `brain-skill`,
`brain-curator`, `brain-orchestrator console`, `brain-ops`,
`brain-prd auto-breakdown`, consolidated root `roles/`, `teams/`, `doctrine/`,
provider matrix и `skills/` — это v25.1.

---
