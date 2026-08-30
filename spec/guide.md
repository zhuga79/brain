# brain — Guide (living documentation)

> Architecture, role registry, CLI/MCP reference, runbooks, decisions, known limits,
> roadmap, learning loop, cheat sheet, glossary.
> Stable contract: see [./contract.md](./contract.md). Top-level entry: [../brain-spec.md](../brain-spec.md).

## TL;DR — за 30 секунд

```bash
# 0. Установка идёт ТОЛЬКО из системного чекаута. Запуск установщика из
#    корня данных перезапишет твой MEMORY.md шаблоном.
cd "$BRAIN_SYSTEM_PATH"

# 1. Один раз настроить
bash setup-brain-v2.sh && bash add-teams-brain.sh && \
bash add-pm-finance-brain.sh && bash add-design-negotiator-brain.sh && \
bash refine-tax-boundaries.sh && bash add-power-features-brain.sh && \
bash patch-brain-run-doctrine.sh

# 1b. Опционально: MCP-режим
bash install-brain-mcp.sh
claude mcp add brain "$HOME/.local/bin/brain-mcp"

# 2. Создать задачу
brain-task add "Проверить договор с X" --role lawyer --prio P1

# 3. Простой режим: одна модель работает по задаче
brain-run --role lawyer --task <id> --agent-id law-1 | claude

# 4. Совет ролей (например, по налоговому вопросу)
brain-task add "Выбрать налоговый режим" --role tax-advisor --mode council
# поправь в active.md: council: [team:finance]
brain-launch <id>                # tmux с 3 окнами разных моделей
brain-council synthesize <id>    # после того как все отписались
brain-run --role arbiter --task <id> --council | claude

# 5. Крупная задача через PRD
brain-task add "Внедрить фичу X" --role architect --mode prd
brain-prd init <id>              # шаблон в ~/brain/prd/<id>.md
# архитектор заполняет ## Subtasks
brain-prd commit <id>            # сабтаски попадают в очередь с deps
brain-task next --role developer # отдаст первый available
```

**Что внутри:** 21 роль в 8 командах, doctrine для разграничения,
блокировки с TTL, git-история всего, MCP-интеграция (42 tool),
tmux-launcher для параллельной работы нескольких моделей.

---




## Содержание

1. [TL;DR](#tldr--за-30-секунд)
2. [Архитектура](#архитектура)
3. [Структура файлов](#структура-файлов)
4. [Ключевые концепции](#ключевые-концепции)
5. [Реестр ролей](#реестр-ролей)
6. [Реестр команд](#реестр-команд)
7. [Doctrine — разграничения между ролями](#doctrine)
8. [Формат задач](#формат-задач)
9. [Lock protocol](#lock-protocol)
10. [Council protocol](#council-protocol)
11. [PRD-режим](#prd-режим)
12. [Wiki — структура и правила](#wiki)
13. [Indexing — поисковый движок и метаданные](#indexing)
14. [CLI-инструменты](#cli-инструменты)
15. [MCP-сервер](#mcp-сервер)
15. [Tmux-launcher](#tmux-launcher)
16. [Git auto-commit](#git-auto-commit)
17. [Подключение CLI-агентов](#подключение-cli-агентов)
18. [Установка](#установка)
19. [Тестирование](#тестирование)
20. [Архитектурные решения](#архитектурные-решения)
21. [Известные ограничения](#известные-ограничения)
22. [Roadmap](#roadmap)
23. [Cheat sheet](#cheat-sheet)
24. [Матрица решений](#матрица-решений)
25. [Глоссарий](#глоссарий)
26. [Версионирование](#версионирование)

---


## Архитектура

```
┌────────────────────────────────────────────────────────────────────┐
│  Любой CLI-агент: Claude Code / Codex / Gemini CLI / Cursor / ... │
└─────────────┬──────────────────────────────────────┬───────────────┘
              │                                      │
       (через CLAUDE.md /                     (через MCP, опц.)
        AGENTS.md /                                  │
        GEMINI.md симлинки)                          │
              │                                      │
              ▼                                      ▼
┌────────────────────────────────────────────────────────────────────┐
│                       ~/brain/ — single source of truth            │
│                                                                    │
│  MEMORY.md  ←  схема системы (правила, escalation matrix)         │
│  roles/     ←  21 persona                                          │
│  teams/     ←  8 алиасов для совета                                │
│  doctrine/  ←  разграничения на стыках ролей                       │
│  tasks/     ←  очередь задач (active.md, done.md)                  │
│  prd/       ←  PRD-документы для крупных работ                     │
│  council/   ←  мнения совета по задачам                            │
│  wiki/      ←  накапливаемое знание + log                          │
│  raw/       ←  источники (immutable)                               │
│  .locks/    ←  атомарные блокировки (TTL)                          │
│  .git/      ←  версионирование всего                               │
└────────────────────────────────────────────────────────────────────┘
              ▲                                      ▲
              │                                      │
        ┌─────┴──────┐                       ┌───────┴────────┐
        │   shell    │                       │  MCP server    │
        │   CLI:     │                       │  (Python,      │
        │ brain-task │                       │   fastmcp)     │
│ brain-lock │                       │  42 tool       │
        │ ...        │                       │                │
        └────────────┘                       └────────────────┘
```

Принципиальные свойства:

- **Memory ≠ contextwindow.** Память живёт в файлах, контекст агента
  собирается перед каждым вызовом из релевантных кусков.
- **Source-based deployment.** Инструменты и шаблоны хранятся в `runtime/bin` и `runtime/templates`, откуда разворачиваются установочными скриптами.
- **No central daemon.** Нет долгоживущего процесса, который «держит»
  состояние. Source of truth — файлы. Демон есть только опционально:
  MCP-сервер для агентов, которые умеют MCP.
- **Concurrency через файловую систему.** Атомарные блокировки через
  `mkdir`. Никаких баз данных.
- **Provider-agnostic.** Любая LLM с CLI или MCP-поддержкой работает с
  одной и той же памятью.
- **Single user, multiple agents.** Система рассчитана на одного
  пользователя, который оркестрирует несколько LLM-сессий.

---


## Ключевые концепции

### Роль (`role`)
Persona-файл `roles/<name>.md`. Описывает: что роль делает, чего не делает,
принципы, шаблоны вывода, рекомендуемую модель, зоны на стыке с другими
ролями. Агент при запуске читает свой role-файл и работает в его рамках.

### Команда (`team`)
Именованный набор ролей (`teams/<name>.md`) для использования в режиме
консилиума. В задаче пишется `council: [team:legal]` — разворачивается в
полный список ролей.

### Doctrine
Документы `doctrine/<name>.md`, которые описывают **стык** между ролями
(не одну роль). Используются когда вопрос системно сложен и требует
явного разграничения. Пример: `tax-boundaries.md` режет налоговую работу
на 4 этапа с явным primary для каждого.

### Режим задачи (`mode`)
- `solo` — одна роль исполняет (default)
- `council` — несколько ролей дают независимые мнения, arbiter синтезирует
- `prd` — крупная работа: architect декомпозирует в developer-сабтаски с deps

### Agent ID
Идентификатор сессии конкретного агента: `<role>-<random-hex>` или
`<provider>-<model>-<short-id>`. Генерируется при старте сессии. Нужен
для блокировок и атрибуции в логе.

### Lock
Атомарная блокировка через `mkdir`. Предотвращает гонки при параллельной
работе нескольких агентов. TTL по умолчанию 600 секунд. Stale-локи
(TTL истёк) автоматически переcхватываются.

---


## Реестр ролей

21 роль в 6 функциональных группах + 1 cross-functional.

### Engineering

| Роль | Ответственность | Рекомендуемая модель |
|---|---|---|
| `architect` | Проектирование, декомпозиция, ADR | claude-opus / gpt-5 / o3 |
| `developer` | Реализация по плану | claude-sonnet / gpt-4o / gemini-pro |
| `reviewer` | Критика кода и решений, поиск дыр | **другой провайдер чем developer** |
| `security` | AppSec/OpSec, threat model, security gates | мощная + другой провайдер |
| `researcher` | Поиск источников, наполнение `raw/` | с web-поиском |
| `linter` | Поддержка wiki: индекс, перекрёстки, чистка | claude-haiku / gpt-4o-mini |
| `arbiter` | Синтез мнений совета | мощная, **отличная от участников совета** |

### Legal

| Роль | Ответственность | Модель |
|---|---|---|
| `lawyer` | Договоры, корпоративное право (ГК РФ) | мощная |
| `compliance` | ФЗ-152, ФЗ-572, ФЗ-187, 115-ФЗ, 259-ФЗ, ГОСТ | мощная |
| `paralegal` | Поиск практики, проверка контрагентов, шаблоны | лёгкая с web-доступом |

### Marketing & Creative

| Роль | Ответственность | Модель |
|---|---|---|
| `strategist` | Позиционирование, ICP, JTBD, GTM | мощная |
| `copywriter` | Тексты лендингов, рассылок, постов | сильная по языку |
| `designer` | UX/UI, brand, design system, UI/UX skill routing | мощная |
| `growth-analyst` | Юнит-экономика, A/B, аналитика | мощная + code execution |

### Project Management

| Роль | Ответственность | Модель |
|---|---|---|
| `pm` | Scope/time/budget/risk, status, RAID | мощная |
| `product` | Discovery, приоритизация, PRD, метрики | мощная |
| `delivery` | Ритмы, разблокировка, WIP, flow metrics | средняя |

### Finance

| Роль | Ответственность | Модель |
|---|---|---|
| `cfo` | Cashflow, юнит-эк., инвест.решения, pricing | мощная + code |
| `accountant` | Первичка, учёт, закрытие периода | средняя |
| `tax-advisor` | Режимы (НПД/УСН/ОСНО/...), сроки, валютный контроль | мощная |

### Cross-functional

| Роль | Ответственность | Модель |
|---|---|---|
| `negotiator` | BATNA/ZOPA, тактика, скрипты переговоров | мощная |

### Принципы диверсификации

- **Reviewer** должен использовать модель **другого провайдера**, чем
  developer/architect — снижает корреляцию ошибок (одинаковые модели
  делают одинаковые слепые пятна).
- **Arbiter** должен быть **отличен от участников совета** по той же причине.
- В `~/brain/.cli-mapping.sh` это зашито в дефолтах: reviewer/linter/
  paralegal/accountant/delivery → `gemini`, остальные → `claude`.

---


## Doctrine

Документы, которые читаются агентом **поверх** role-файла. Автоматически
подгружаются `brain-run` в промпт, если упомянуты в роли.

### `tax-boundaries.md`

Решает многолетний конфликт «кто отвечает за налоги». Налоговая работа
режется на 4 этапа, у каждого свой primary:

```
ЭТАП 1: УЧЁТ      → accountant   (что было)
ЭТАП 2: РАСЧЁТ    → tax-advisor  (сколько в бюджет)
ЭТАП 3: СТРУКТУРА → tax-advisor + lawyer (как сделать)
ЭТАП 4: ЗАЩИТА    → tax-advisor (существо) + lawyer (процесс)
```

**Запреты, прописанные в каждой из 4 ролей:**
- `lawyer` не считает сумму налога
- `compliance` не считает налог и не выбирает режим
- `accountant` не интерпретирует НК и не оптимизирует
- `tax-advisor` не пишет договор и не идёт в суд

Документ содержит таблицу из 10 типовых вопросов с маршрутизацией к
primary и нужным council-ролям, а также flowchart эскалации.

### `legal-vs-compliance.md`

Простой тест: `lawyer` = что ЗАПИСАНО (разовый документ),
`compliance` = что ТРЕБУЕТСЯ КАК ПРОЦЕСС (регулярная отчётность).

Содержит таблицу пограничных случаев (разовый документ ПД vs политика ПД,
NDA vs программа защиты КТ, иск ФАС vs соответствие 38-ФЗ как процесс)
и правило подключения обоих через `[lawyer, compliance]` совет.

---


## CLI-инструменты

Все скрипты в `~/.local/bin/`. Должны быть в `$PATH`.

### `brain-task` — управление задачами

```
brain-task                              показать active.md
brain-task show <id>                    подробности задачи
brain-task next [--role R]              верхняя АВАИЛАБЛЬНАЯ задача (учитывая deps)
brain-task list [--role R] [--mode M]   фильтрованный список
brain-task deps <id>                    граф зависимостей задачи (○◐●✗)
brain-task add "<text>" [--role R] [--mode M] [--prio P0|P1|P2]
brain-task take <id> --as <agent-id>           лок + пометить [~]
brain-task release <id> --as <agent-id>        снять лок + вернуть [ ]
brain-task complete <id> --as <agent-id>       пометить [x] + перенос в done.md
brain-task block <id> "reason"          пометить [!] с причиной
brain-task log [N]                      последние N записей log.md (default 30)
brain-task webhook-replay               переотправить записи из .webhooks/dead-letter.jsonl
```

Все мутирующие операции делают git auto-commit.

### `brain-lock` — блокировки

```
brain-lock acquire <id> --as <agent-id> [--ttl 3600]
brain-lock release <id> [--as <agent-id>]
brain-lock refresh <id> --as <agent-id> [--ttl 3600]
brain-lock status [<id>]
brain-lock cleanup
```

Возвращаемые статусы:
- `ok` — захвачен
- `locked by: <agent> (age Xs, ttl Ys)` — занят
- `released` — освобождён
- `cleaned N stale locks` — после cleanup

### `brain-council` — оркестрация совета

```
brain-council start <id>             создать skeleton-файлы для всех ролей
brain-council status <id>            кто отписался, кто нет
brain-council synthesize <id>        создать skeleton synthesis.md
brain-council check <id>             проверить готовность совета (guardrails)
brain-council list                   все активные советы
brain-council teams                  список доступных команд
```

Поддерживает `team:<name>` синтаксис в `council:` поле задачи.

### `brain-prd` — PRD workflow

```
brain-prd init <task-id>             создать prd/<id>.md по шаблону
brain-prd commit <task-id>           распарсить ## Subtasks, залить в active.md
brain-prd status <task-id>           прогресс по сабтаскам с маркерами
brain-prd list                       все PRD
```

При commit:
- Локальные `s1, s2, ...` разворачиваются в `<parent>-s1, <parent>-s2, ...`.
- `depends_on: [s1]` переписывается в полные id.
- Каждому сабтаску добавляется `parent: <parent-id>`.
- PRD получает `status: committed`.

### `brain-phase` — управление жизненным циклом фаз разработки

```
brain-phase init <N> [title]         создать PRD и инициализировать билеты для фазы N
brain-phase close <N>                сгенерировать release notes, прогнать smoke-тесты и поставить тег
```

Упрощает создание и закрытие фаз разработки (крупных вех проекта). `init` автоматически создает parent-задачу
и вызывает `brain-prd init`. `close` проверяет статус фазы, пишет Release Notes и вызывает `brain-release tag`.

### `brain-launch` — tmux-сессия для совета

```
brain-launch <task-id> [--session NAME] [--dry-run] [--watch] [--auto-next] [--handoff-on-limit]
```

Действия:
1. Извлекает `council:` из задачи.
2. Разворачивает team-алиасы.
3. Создаёт совет если ещё нет.
4. Поднимает tmux-сессию с одним окном на роль.
5. Каждое окно: `brain-run --role X --task Y --agent-id <auto> | <CLI for X>`.

Флаги:

- `--dry-run` — не запускать tmux, только вывести что бы запустилось. Не создаёт council-директорию.
- `--watch` — показать статус окон уже запущенной сессии (требует tmux и живую сессию).
- `--watch --dry-run` — вывести план наблюдения (session name, роли, что будет опрашиваться) без запуска tmux. Не создаёт council-директорию.
- `--auto-next` — после завершения текущей задачи автоматически взять следующую open-задачу (lock protocol соблюдается). Работает с `--watch`.
- `--watch --auto-next --dry-run` — вывести план auto-next без side effects: текущую задачу, критерии завершения, lock plan, следующий тикет.
- `--handoff-on-limit` — обернуть CLI-команду через `brain-handoff run`; при 429/quota/resource/context-limit ошибке создаётся handoff для следующего оркестратора.

`--dry-run` в любой комбинации с `--watch` / `--auto-next` не пишет ничего: ни
в `active.md`, ни в `council/`, ни в `.locks/`, ни в git, ни в tmux. Это
контракт, а не свойство реализации — он закреплён кейсом
`tests/cases/100-launch-watch-safety-stop.sh` после инцидента 2026-08-14, когда
«показать план» пометило `[~]` одиннадцать задач за две минуты.

Standalone watch-loop (`brain-launch --watch` без task-id):

- берёт только `surface: headless` — interactive-задача идёт в видимое окно
  (`docs/decisions/decision-interactive-surface.md`);
- `--wip N` — сколько задач держать в работе одновременно (default 1);
- `--max-failures N` — стоп после N подряд неудачных запусков (default 3);
- `--max-tasks N` — жёсткий предел задач за прогон (default 0 = без предела);
- задача, чей запуск не удался, возвращается в очередь (`[~]` → `[ ]`), а не
  остаётся висеть в работе.

Env-переменные для watch:
- `BRAIN_WATCH_POLL_SEC` — интервал опроса в секундах (default: 5).
- `BRAIN_WATCH_WIP`, `BRAIN_WATCH_MAX_FAILURES`, `BRAIN_WATCH_MAX_TASKS` —
  умолчания для одноимённых флагов watch-loop.

Mapping роль → CLI задаётся в `~/brain/.cli-mapping.sh`:

```bash
cli_for_architect="$CLAUDE_CMD"
cli_for_reviewer="$GEMINI_CMD"        # диверсификация
cli_for_developer="$CLAUDE_CMD"
# ... etc
CLI_DEFAULT="$CLAUDE_CMD"
```

Дефис в имени роли заменяется на подчёркивание: `growth-analyst` →
`cli_for_growth_analyst`.

### `brain-handoff` — передача оркестратора при лимитах

```
brain-handoff create --reason limit-exhausted --from <agent-id> --to-role <role> [--task <id>]
brain-handoff create --reason manual --from <agent-id> --to-role <role> --json
brain-handoff show [--json]
brain-handoff run --task <id> --agent <agent-id> --to-role <role> -- <command...>
```

`brain-handoff create` пишет `$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md`:
текущий `brain-status`, provider matrix summary, active queue snapshot и
готовые команды для следующего CLI. Команда логирует событие
`orchestrator-handoff` в `wiki/log.md`.

`--json` возвращает stable schema (`schema_version: 1`) для передачи состояния
другим CLI без Markdown parsing. Markdown output остаётся совместимым.

`brain-handoff run` запускает переданную CLI-команду, возвращает её исходный
exit code и при ошибках вида `429`, `Too Many Requests`, `RESOURCE_EXHAUSTED`,
`quota`, `rate limit`, `context length`, `token limit` создаёт handoff
автоматически. Это рекомендуемый wrapper для долгих CLI-сессий:

```bash
brain-handoff run --task "$TID" --agent "$AGENT" --to-role developer -- \
  gemini -m gemini-3-flash-preview -p "$PROMPT" --output-format text
```

### `brain-orchestrator` — fallback на другой CLI при лимите

```
brain-orchestrator run --task <id> --agent <agent-id> --to-role <role> \
  --fallback "<fallback command>" -- <primary command...>
```

`brain-orchestrator` запускает primary через `brain-handoff run`. Если primary
завершился с non-zero и в stdout/stderr есть `429`, `RESOURCE_EXHAUSTED`,
`quota`, `rate limit`, `context length` или `token limit`, Brain сначала пишет
`$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md`, затем запускает fallback command.

Обычные ошибки без limit-pattern не переключают оркестратор: исходный exit code
сохраняется, fallback пропускается.

```bash
brain-orchestrator run \
  --task "$TID" \
  --agent gemini-primary \
  --to-role developer \
  --fallback "claude -p /tmp/brain-next-prompt.md" \
  -- gemini -m gemini-3-flash-preview -p "$PROMPT" --output-format text
```

### `brain-provider` — cached provider health

```
brain-provider status [--json] [--role <role>] [--provider <name>] [--model <id>]
brain-provider refresh --provider <name> --model <id> [--timeout N] [--yes] [--json]
brain-provider mark --provider <name> --model <id> --status <status> --reason <text> --yes [--json]
brain-provider clear --provider <name> --model <id> --yes [--json]
```

`status` read-only. `refresh` без `--yes` — dry-run и не пишет cache.
Единственный writer provider health cache — `brain-provider`; dashboard,
`brain-status`, MCP и SSE читают только `$BRAIN_PATH/.provider-health.json`.

### `brain-skill` — управление навыками (Phase 20)

```
brain-skill list                             # Показать все навыки, их роли и поддерживаемые клиенты
brain-skill mount <skill> --to-role <role>   # Разрешить использование скилла для роли
brain-skill unmount <skill> --from-role <role> # Запретить использование скилла
brain-skill ingest-book <path> --to-role <role> # Парсинг документов в knowledge skills и wiki глоссарии
```

Обеспечивает JIT (Just-In-Time) инъекцию навыков. Во время старта `brain-run`, все привязанные к роли скиллы динамически обновляют локальный конфиг
соответствующего CLI-клиента (`.claude/settings.local.json`, `.gemini/settings.json`, `.opencode.json` и т.д.).

**Phase 23 (Skill-Aware Routing & Fallback):**
- **Platform Pinning:** Если задача требует навыка (`requires: [skill_name]`), и этот навык работает только в определенном клиенте (поле `supported_clients: [claude]` в `SKILL.md`), `brain-launch` автоматически направит эту задачу на указанный клиент, проигнорировав дефолтную модель для роли.
- **On-the-Fly Generation:** Если требуемый задачей навык отсутствует в `$BRAIN_PATH/skills/`, `brain-launch` проверит наличие квот на кодинг-модели и автоматически создаст блокирующую задачу (P0) для генерации этого навыка "на лету" разработчиком, заблокировав исходную задачу до его готовности.

### `brain-curator` — автономный куратор навыков (Phase 21)

```
brain-curator monitor                 # Анализ логов на starvation triggers (составляет wishlist.json)
brain-curator search                  # Поиск решений (скиллов/MCP) для открытых элементов wishlist
brain-curator synthesize              # Генерация Proposals для найденных скиллов
brain-curator rank-models             # Парсинг бенчмарков + API стоимости -> IQ/Cost ratio (Model Fleet Efficiency Report)
brain-curator monitor-limits          # Мониторинг кросс-CLI rate-limits и здоровья флота моделей
```

Проактивный фоновый агент (роль `skill-curator`), который ищет недостающие компетенции и предлагает
монтирование новых скиллов, а также динамически маршрутизирует модели, исходя из их IQ, стоимости и доступности.

### `brain-workspace` — folder-native workspaces

```
brain-workspace discover --root <path> [--json]
brain-workspace summary --root <path>
brain-workspace nearest <path>
brain-workspace tasks --workspace <path> [--role R] [--state open|in-progress|done|blocked|all] [--json]
brain-workspace next --workspace <path> [--role R] [--json]
brain-workspace take --workspace <path> <task-id> --as <agent-id>
brain-workspace complete --workspace <path> <task-id> --as <agent-id> --model <provider-model-version> [--summary "..."]
brain-workspace init-template --out <path>
```

Workspace is opt-in and folder-native: a folder becomes a Brain workspace when
it contains `BRAIN.md`. Optional `TASKS.md` and `LOG.md` live beside the actual
documents. Brain does not maintain a hand-edited central registry; global views
are generated by scanning approved roots for `BRAIN.md`.

Pilot examples:

```bash
brain-workspace discover --root /path/to/workspace-alpha
brain-workspace summary --root "/path/to/workspace-beta"
brain-orchestrator console --workspace "/path/to/workspace-alpha/child" --dry-run
```

`init-template` refuses to overwrite existing `BRAIN.md`, `TASKS.md` or
`LOG.md`. Use it only after approving writes to the target folder.

Local task commands only edit the folder-local `TASKS.md` and `LOG.md`.
They do not create a central task registry. Use them when an agent is working
inside one project folder and needs a small queue close to the documents.

#### Scope boundary: deliberately limited, not a second root queue

A folder-native workspace is a **deliberately limited** contour, not a
folder-scoped clone of the root queue. This is decided, not an oversight —
see `docs/decisions/decision-runtime-core-boundaries.md`. Concretely:

- `brain-task`, `brain-lock` and `brain-council` never read a workspace's
  `TASKS.md`. They operate on `$BRAIN/tasks/active.md` only, and
  `brain-validate` (`validate_queue_scope`) rejects a `client:` task placed
  there — client/case work belongs in the workspace folder, not the root
  queue, and the two queues are not meant to merge. Concurrency, ownership
  and completion for a workspace's own queue are `brain-workspace
  take|complete`, which already has its own lock and recovery journal
  (`brain_workspace.py`); there is no second implementation to reconcile it
  with.
- `brain-workspace` never consults `BRAIN_PATH` or cwd auto-detection: it
  resolves the workspace purely from an explicit `--workspace` or the
  nearest parent `BRAIN.md` (`find_nearest_workspace`). If pointing
  `brain-task`/`brain-lock` at a workspace folder seems necessary, that is a
  sign the work belongs to the root queue instead, not a gap to work around
  with `BRAIN_PATH`.
- `brain-validate` does not check a workspace folder's contents at all: it
  detects the `BRAIN.md` marker and returns a single INFO issue pointing at
  `brain-workspace` instead of applying the root schema (`raw/`, `wiki/`,
  `tasks/active.md`, `EXCLUSIVE_SYSTEM_DIRS`, ...). A workspace folder is
  free to contain `docs/`, `tests/`, `config/` or any other name for its own
  purposes — those restrictions exist only for the split-root system/data
  boundary and were never meant to reach folder-native workspaces.
- Case-specific personas (a persona relevant to one case only) are **not** a
  supported workspace-local mechanism: a workspace's `Role Policy` section
  (`core`/`available`/`gated`/`blocked`) scopes which *existing* system roles
  apply here, it does not define new ones. A persona needed only inside one
  workspace stays as prose guidance in that workspace's `BRAIN.md`; a persona
  that should be recognized by `brain-council` and the routing matrix
  system-wide is added once, normally, to the shared `roles/` directory.

#### Workspace role policy

Each workspace `BRAIN.md` is also the local authority for role access. Brain
must not infer a central document registry from these files: global views are
only scan results, while permissions and gates remain in the folder itself.

Use this contract for new or upgraded workspaces:

```markdown
## Workspace Profile

type: legal-commercial-contract
primary_role: pm

## Role Policy

core:
- pm

available:
- lawyer
- paralegal
- accountant
- reviewer

gated:
- tax-advisor
- compliance
- negotiator
- developer

blocked:
- none

## Action Gates

requires_user_approval:
- отправка писем
- изменение подписанных документов
- перемещение актов, отчетов и архивов
- финальные правовые выводы перед отправкой претензии
- налоговая квалификация
```

Meanings:

- `core` roles may run normal workspace tasks without extra role approval.
- `available` roles may be assigned local tasks.
- `gated` roles may be assigned local tasks, but their sensitive actions must
  be confirmed by the user before execution.
- `blocked` roles must not receive local tasks in this workspace.
- Unknown roles are blocked by default unless the workspace explicitly allows
  them in `core`, `available` or `gated`.
- Legacy workspaces that have no `Role Policy` and no `Allowed Roles` keep
  permissive behavior until they are upgraded.

Action gates are stricter than role access. If an action appears under
`requires_user_approval`, an agent must stop and get explicit user approval
even if its role is otherwise allowed.

#### Folder-local `TASKS.md`: format and fail-closed dependencies

A workspace's `TASKS.md` is a folder-local queue parsed by `brain_workspace.py`.
Task blocks use the same continuation-line format as the root queue:

```
- [ ] [P1] local-001 - First task
      role: developer
      acceptance: State the concrete completion check.

- [ ] [P2] local-002 - Second task depending on the first
      role: developer
      depends_on: [local-001]
      acceptance: Runs after local-001 is done.
```

`depends_on` syntax is exact:

- `depends_on: [task-id-1, task-id-2, ...]` — a bracketed, comma-separated list
  of task ids that must be done before this task becomes available.
- Empty components are rejected: `[,]`, `[dep,]`, `[,dep]`, `[dep,,other]`.
- Duplicate ids inside the list are rejected (`[task-x, task-x]`).
- The `depends_on` field may appear at most once per task — a repeated field on
  the same continuation line or across lines is rejected. Field order on the
  line does not matter (shared `grammar.parse_fields` parser).

Parsing is fail-closed: `parse_local_tasks` rejects malformed or duplicate
`depends_on`, duplicate task ids, self- and cyclic dependencies, and missing
dependencies `before` building the graph, selecting or mutating anything. The
operations behave as follows:

- `next_local_task` — skips tasks with unmet dependencies (returns `None` when
  nothing is available). Never mutates files.
- `take_local_task` — if a task has unmet dependencies, rejects with `ValueError`
  before mutating `TASKS.md` or `LOG.md`; the task stays `[ ]` and no log entry
  is written.
- `complete_local_task` — if a task has unmet dependencies, rejects with
  `ValueError` before mutating `TASKS.md` or `LOG.md`; the task stays `[~]` and
  no log entry is written.

Contending `take`/`complete` calls serialize on the workspace queue lock
(`.workspace-queue.lock`); a take that wins the lock is the only one that
mutates the queue, so exactly one contender can take a task.

### `brain-federation` — controlled federation import and sync

```
brain-federation support [--json]
brain-federation preflight [--repo <path>] [--brain <path>] [--json]
brain-federation tasks-check --active <path> [--done <path>] [--json]
brain-federation plan --repo <path> [--brain <path>] [--json] [--out <plan.json>]
brain-federation import-tasks --plan <plan.json> --as <agent-id> [--yes] [--json]
brain-federation write-wiki-proposals --plan <plan.json> --as <agent-id> [--yes] [--json]
brain-federation sync [--repo <path>] [--json]
brain-federation merge-tasks --base <path> --local <path> --remote <path> [--out <path>]
```

Phase 10/11 команды обеспечивают read-only проверки и plan-first импорт (через JSON планы).
Phase 22 добавляет `sync` и 3-way `merge-tasks`:

- `sync` автоматически делает безопасный `git pull --rebase` и `git push`. Ошибки возвращаются как findings.
- `merge-tasks` делает 3-way merge `active.md`, корректно объединяя статусы (приоритет у завершенных) и метаданные (deps, council).
- `preflight` теперь проверяет `federated-lock-warning` (конфликт измененных задач, залоченных локально).

- `plan` read-only, кроме явного `--out`; включает `task_imports`,
  `wiki_proposals`, `plan_id`, `generated_at` и source fingerprints.
- `import-tasks` по умолчанию dry-run. С `--yes` импортирует только safe open
  tasks из плана, отказывает stale plans, `block` findings, duplicates,
  `[~]` и active/done conflicts. Пишет только `tasks/active.md` и `wiki/log.md`.
- `write-wiki-proposals` по умолчанию dry-run. С `--yes` пишет только
  `$BRAIN_PATH/proposals/federation/<timestamp>/` (`manifest.json`, `.md`,
  `.diff`, `.meta.json`), никогда не пишет `wiki/` или `raw/`.

Exit code:

- `0` — success/no blocking findings;
- `1` — safety gate refused (`block`, stale plan, duplicate/conflict);
- `2` — usage/input/schema/io error.

`preflight` блокирует runtime/generated файлы (`.locks/`, `.brain/`,
`.provider-health.json`, `.cli-mapping.sh`,
`handoff/ORCHESTRATOR_HANDOFF.md`, `wiki/_views/`), raw rewrites,
`protected: true`/`curation: human` wiki edits и опасные task conflicts.
Provider matrix changes возвращаются как `review`, включая command/model
изменения, без live probes.

Optional secret scanning is controlled by `BRAIN_SECRET_SCANNER_CMD`. If set,
Brain runs that local command with the repo path as the final argument and
accepts JSON-lines findings. Missing or failing scanners produce `warn` and the
built-in regex fallback still runs; no install or network action is attempted.

### `brain-sync-cycle` — LAN-safe sync installer

```
brain-sync-cycle --dry-run [--brain <path>] [--repo <path>] [--json]
brain-sync-cycle --apply [--brain <path>] [--repo <path>] [--json]
brain-sync-cycle install-systemd [--brain <path>] [--repo <path>] [--interval 5min] [--enable|--no-enable] [--json]
```

`brain-sync-cycle` is the user-facing wrapper for single-user LAN
synchronization between Brain checkouts. It keeps the federation safety boundary:
only git-tracked durable Brain state is synchronized, while runtime-local state
(`.locks/`, `.brain/`, provider cache, CLI mapping and generated views) remains
local.

- `--dry-run` checks whether automatic sync is safe and reports `would_sync`.
- `--apply` refuses tracked runtime files and dirty tracked durable files before
  calling `brain-federation sync`; after successful sync it rebuilds the local
  index by default.
- `install-systemd` writes `brain-sync.service` and `brain-sync.timer` user
  units. It does not enable the timer unless `--enable` is passed.

### UI/UX skill pack

UI/UX skills live under:

```text
skills/uiux/core/
skills/uiux/brain/
skills/uiux/handoff/
```

Canonical UI/UX council:

```text
[product, designer, developer, reviewer]
```

Use it for any new screen, flow or component that affects more than one role.
`designer` is the primary UI/UX role. `product` owns JTBD/scope/success
metrics, `developer` owns implementation details, `copywriter` owns final
microcopy, and `reviewer` owns quality review. `linter` owns skill-pack hygiene
and stale references.

Contract: `handoff/2026-05-07-uiux-skill-contract.md`.

### `brain-run` — собрать промпт для CLI

```
brain-run --role R --task ID [--council] [--agent-id A]
```

Печатает на stdout:
1. `# === SYSTEM ===` — введение
2. `# === MEMORY.md ===` — полный текст MEMORY.md
3. `# === ROLE: <name> ===` — полный текст role-файла
4. `# === DOCTRINE ===` — все doctrine-файлы, упомянутые в role-файле
   (автоматически по grep)
5. `# === RECENT LOG ===` — последние 10 записей log.md
6. `# === WIKI INDEX ===` — содержимое wiki/index.md
7. `# === TASK: <id> ===` — блок задачи из active.md
8. `# === COUNCIL OPINIONS ===` — если `--council`, мнения других ролей
9. `# === INSTRUCTIONS ===` — что делать (acquire lock, take, complete...)

Pipe в любой CLI:
```bash
brain-run --role architect --task t-... | claude
brain-run --role developer --task t-... | codex
brain-run --role reviewer  --task t-... | gemini
```

Если `--agent-id` не задан — генерится `<role>-<random4hex>`.

### `brain-link` — подключить память к проекту

```
brain-link
```

Создаёт в текущей директории симлинки:
```
./CLAUDE.md      → ~/brain/MEMORY.md
./AGENTS.md      → ~/brain/MEMORY.md
./GEMINI.md      → ~/brain/MEMORY.md
./.cursorrules   → ~/brain/MEMORY.md
```

Если файл уже существует и не симлинк — пропускает (не перезаписывает).

### `brain-ingest` — загрузка источника

```
brain-ingest [file|-] [--slug SLUG] [--title TITLE] [--url URL] [--type TYPE] [--no-index]
```

Действия:
1. Читает Markdown/text из файла, stdin (`-`) или inline-аргумента.
2. Сохраняет в `raw/<slug>.md` с метаданными и запрещает тихую перезапись.
3. Создаёт `wiki/source-<slug>.md` как source-summary skeleton, если его ещё нет.
4. Обновляет `wiki/index.md` и логирует операцию `ingest`.

### `brain-validate` — проверка контрактов

```
brain-validate [--warnings-as-errors]
```

Проверяет целостность wiki/raw/task refs: frontmatter, типы страниц, даты,
`sources`, wikilinks и `ref:` в задачах. Не проверяет «истинность» ручного
контента и не считает источник выше human-curated wiki.

### `brain-lint` — глубокий аудит wiki

```
brain-lint [--fix-index]
```

Поиск orphan-страниц, missing wikilinks, дублей, stale pages, broken task refs
и stale locks. `--fix-index` пересобирает только `wiki/index.md`.

### `brain-index` — управление индексом

```
brain-index rebuild [--with-obsidian]     полная пересборка всех файлов индекса
brain-index status                        информация о текущем состоянии индекса
brain-index page <slug>                   запись страницы из pages.json
brain-index backlinks <slug>              обратные ссылки из links.json
brain-index sources [raw/foo.md]          карта raw/source-summary/wiki pages
brain-index stale                         проверка freshness индекса
brain-index export-obsidian               синхронизация метаданных для Obsidian
```

### `brain-graph` — Knowledge Graph Query CLI

```
brain-graph query <slug>                  показать связи конкретного узла
brain-graph stats                         показать статистику графа (узлы, связи)
brain-graph export <file> [--format dot]  сохранить граф в dot, json или tsv
```

Анализирует связи `related:` и `sources:` между Markdown-страницами и задачами.
Используется для построения Obsidian Canvas и визуализации связности знаний.

### `brain-search` — полнотекстовый поиск

```
brain-search "запрос"                     поиск по всей памяти (BM25)
brain-search "запрос" --type concept      фильтрация по типу
brain-search "запрос" --limit 20          лимит результатов
brain-search "запрос" --json              вывод в машиночитаемом формате
```

### `brain-vector` — опциональный векторный поиск

```
brain-vector index rebuild                собрать/пересобрать векторный индекс
brain-vector search "<q>" [--top-k N]    семантический поиск (default top-k=5)
brain-vector status                       статус индекса: размер, документы, модель
brain-vector support [--json]             support matrix: ChromaDB optional, BM25 required
```

Требует `chromadb` и `sentence-transformers`. При отсутствии — exit 1 с
инструкцией `pip install`. Индекс в `$BRAIN_PATH/.brain/vector/`.
**Не заменяет** `brain-search` (BM25).

### `brain-task` webhook — уведомление о завершении

При вызове `brain-task complete <id> --as <agent>` Brain публикует webhook-событие,
если задана переменная `BRAIN_WEBHOOK_URL`.

**Env-переменные:**

| Переменная | Описание | Default |
|---|---|---|
| `BRAIN_WEBHOOK_URL` | HTTP endpoint для POST события | — (webhook отключён) |
| `BRAIN_WEBHOOK_TIMEOUT_SEC` | Таймаут подключения (секунды) | `3` |

**Payload (JSON):**
```json
{
  "event":      "task-done",
  "task_id":    "<task-id>",
  "agent_id":   "<agent-id>",
  "state":      "done",
  "timestamp":  "YYYY-MM-DDTHH:MM:SSZ",
  "brain_path": "/path/to/brain"
}
```

Ошибка доставки (timeout, 5xx, сетевая) → `WARN` в stderr, задача всё равно завершается.
Proxy-переменные окружения игнорируются (всегда прямое соединение).

### `brain-status` — статус оркестрации

```
brain-status                              краткая сводка (задачи, локи, индекс)
brain-status --json                       вывод в формате JSON
```

Инструмент только для чтения, не меняет файлы и не делает коммитов.

### `brain-doctrine` — браузер доктрин

```
brain-doctrine list                       список слагов доктрин
brain-doctrine list --json                вывод в формате JSON
brain-doctrine show <slug>                содержимое файла доктрины
brain-doctrine show <slug> --json         вывод в формате JSON
brain-doctrine search <query>             поиск по всем файлам доктрин (case-insensitive)
brain-doctrine search <query> --json      вывод в формате JSON
```

Форматы JSON:

- `list --json` → `{"doctrines": [{"slug": "...", "path": "..."}]}`
- `show <slug> --json` → `{"slug": "...", "path": "...", "content": "..."}`
- `search <query> --json` → `{"query": "...", "results": [{"slug": "...", "path": "...", "snippet": "..."}]}`

Инструмент только для чтения, не меняет файлы. Читает `$BRAIN_PATH/doctrine/*.md`.

Проверка:

```bash
brain-doctrine --help
brain-doctrine list
brain-doctrine show tax-boundaries
brain-doctrine search "accountant"
```

### `brain-dashboard` — HTML-дашборд оркестрации

```
brain-dashboard export                    сгенерировать статический HTML-дашборд
brain-dashboard export --out <path>       сохранить в указанный файл
brain-dashboard --brain <path> export     указать Brain path явно
brain-dashboard serve [--port N] [--host 127.0.0.1]
                                           live-режим: HTTP-сервер с SSE обновлениями
```

**Статический режим (`export`):** Генерирует
`$BRAIN_PATH/wiki/_views/brain-dashboard.html` — read-only страница без удалённых
ресурсов. Показывает задачи, фильтры/grouping по role/provider, handoff/limits,
блокировки, консилиумы, статус индекса, Obsidian-views, audit log (последние 20
записей из `wiki/log.md`).

**Live-режим (`serve`):** HTTP-сервер на `127.0.0.1:8765` (по умолчанию).

- `GET /` — живая HTML-страница с `EventSource` (обновляется без перезагрузки).
- `GET /?task=<id>` — фильтр задач по id.
- `GET /events` — SSE-поток (5-секундный интервал), обновляет счётчики.
- `GET /api/audit[?task=<id>]` — JSON: последние 20 write-операций из лога.
- `POST /api/tasks/<id>/take?as=<agent>` — взять задачу (через `brain-task take`).
- `POST /api/tasks/<id>/release?as=<agent>` — отказаться.
- `POST /api/tasks/<id>/complete?as=<agent>` — завершить.
- `POST /api/launch?workspace=<path>&task=<id>&role=<role>&client=<cli>[&dry_run=1]`
  — запустить allowlisted workspace-agent command через `brain-orchestrator console`.

Write actions всегда требуют `X-Brain-Confirm: 1`. Если задан
`BRAIN_DASHBOARD_AUTH_TOKEN`, POST также требует `X-Brain-Token`, а read
endpoints (`/`, `/events`, `/api/*`) требуют `X-Brain-Token` или `?token=...`.
Non-loopback bind через `--host 0.0.0.0` без token не стартует.

Launch actions are intentionally narrow: the dashboard accepts only
`workspace`, `task`, `role` and an allowlisted `client` (`codex`, `claude`,
`gemini`, `ollama`, `opencode`, `kilocode`). The server builds the
`brain-orchestrator console` command; the browser never submits arbitrary shell.
Use `dry_run=1` to preview the launch plan without opening a terminal.

Для scripted API предпочитай header `X-Brain-Token`. Query-token нужен для
browser/SSE bootstrap и считается чувствительным URL. Live dashboard сохраняет
`?token=` в `localStorage.brainDashboardToken` и сразу очищает видимый URL через
`history.replaceState`, сохраняя остальные query-параметры.

Проверка:

```bash
brain-dashboard export
# → $BRAIN_PATH/wiki/_views/brain-dashboard.html

brain-dashboard serve &
curl -s http://127.0.0.1:8765/api/audit | python3 -c "import json,sys; print(json.load(sys.stdin)['count'])"
```

### `brain-mcp` — запуск MCP-сервера

```
brain-mcp                              # stdio transport (Claude Desktop / MCP CLI)
brain-mcp --http                       # HTTP/SSE transport (по умолчанию 127.0.0.1:8766)
brain-mcp --http --port N              # указать порт (1–65535)
brain-mcp --http --host <addr>         # указать адрес (non-empty)
```

При запуске с `--http` выводит стартовый баннер в stderr:

```
Brain MCP server starting (SSE/HTTP transport)
  endpoint : http://127.0.0.1:8766/sse
  brain    : /home/user/brain
  tools    : 42
```

Ошибки: невалидный порт (0 или >65535) или занятый адрес — завершается с кодом 1
и понятным сообщением в stderr.

См. раздел [MCP-сервер](#mcp-сервер).

### `brain-shell` — интерактивная оболочка Brain

```
brain-shell                       # интерактивный REPL
brain-shell --yes                 # авто-подтверждение write-операций
```

Интерактивная оболочка для управления Brain: поиск, задачи, локи, статус.

**Команды:**

```
status                     показать brain-status
search <query>             BM25-поиск по wiki
preset <role>              установить роль (architect / developer / reviewer …)
take <id> [--as <agent>]   взять задачу
release <id>               освободить лок
complete <id>              завершить задачу
help                       список команд
exit                       выход
```

Write-операции (`take`, `release`, `complete`) запрашивают подтверждение интерактивно,
если не передан флаг `--yes`.

---


## MCP-сервер

Python+FastMCP сервер, экспортирует операции brain как tools для
LLM-агентов с MCP-поддержкой.

### Установка

```bash
bash install-brain-mcp.sh
# создаёт venv в ~/.local/share/brain-mcp/.venv
# ставит fastmcp + mcp пакеты
# создаёт launcher brain-mcp в ~/.local/bin/
```

### Подключение к Claude Code

```bash
claude mcp add brain "$HOME/.local/bin/brain-mcp"
```

После этого все tools доступны как `brain__<name>`.

### Полный список tools (42)

#### Tasks (9 tools)

```python
list_tasks(role: str = "", mode: str = "", status: str = "open") -> dict
# status: open | in_progress | blocked | done | all

get_task(task_id: str) -> dict

get_next_task(role: str = "") -> dict
# учитывает depends_on

add_task(text: str, role: str = "developer", mode: str = "solo",
         priority: str = "P2",
         council: list[str] | None = None,
         depends_on: list[str] | None = None,
         acceptance: str = "TODO") -> dict
# возвращает {"id": "t-...", "status": "added"}

take_task(task_id: str, agent_id: str, ttl: int = 3600) -> dict
# acquire_lock + установка [~] + started/by

release_task(task_id: str, agent_id: str = "") -> dict
# release_lock + возврат к [ ]

complete_task(task_id: str, agent_id: str = "", summary: str = "") -> dict
# [x] + перенос в done.md + release_lock + git commit

block_task(task_id: str, reason: str) -> dict

get_task_deps(task_id: str) -> dict
# рекурсивный обход depends_on, возвращает дерево
```

#### Locks (5 tools)

```python
acquire_lock(task_id: str, agent_id: str, ttl: int = 3600) -> dict
# {"status": "ok"} | {"status": "locked", "owner": ..., "age_seconds": ..., "ttl": ...}
# Stale-локи перехватываются автоматически.

release_lock(task_id: str, agent_id: str = "") -> dict
# Если agent_id передан — проверяется владение.

refresh_lock(task_id: str, agent_id: str, ttl: int = 3600) -> dict

lock_status(task_id: str = "") -> dict
# Без аргумента — все локи.

cleanup_locks() -> dict
# {"cleaned": N}
```

#### Council (5 tools)

```python
council_start(task_id: str) -> dict
# Создаёт skeleton-файлы для всех ролей из council: поля.

council_status(task_id: str) -> dict
# Кто отписался, кто pending.

add_council_opinion(task_id: str, role: str, agent_id: str, model: str,
                    position: str, reasoning: str,
                    risks: str, recommendation: str) -> dict
# Заполняет council/<id>/<role>.md полностью.

get_council_opinions(task_id: str, role: str = "") -> dict
# Без role — все готовые мнения (без TODO).

synthesize_council(task_id: str, arbiter_agent: str,
                   positions: dict, agreement: str, disagreement: str,
                   decision: str, reasoning: str,
                   open_questions: str = "",
                   follow_up_tasks: list[str] | None = None) -> dict
# Создаёт synthesis.md.
```

#### Memory & Roles (5 tools)

```python
get_memory() -> dict
# содержимое MEMORY.md

get_role(role: str) -> dict
# содержимое roles/<role>.md

list_roles() -> dict
# {"roles": [...]}

list_teams() -> dict
# {"teams": {"engineering": [...], "legal": [...], ...}}

get_doctrine(name: str = "") -> dict
# Без аргумента — список доктрин. С аргументом — содержимое.
```

#### Wiki (7 tools)

```python
search_wiki(query: str, max_results: int = 10) -> dict
# Naive keyword search по wiki/, возвращает {"results": [{"path", "title", "snippet"}]}

read_wiki_page(path: str) -> dict
# Path: wiki/foo.md или просто slug "foo"

write_wiki_page(slug: str, content: str,
                page_type: str = "concept",
                tags: list[str] | None = None,
                sources: list[str] | None = None,
                related: list[str] | None = None,
                title: str = "",
                curation: str = "agent",
                protected: bool = False,
                source_policy: str = "",
                force: bool = False,
                update_index: bool = False) -> dict
# Создаёт/перезаписывает с frontmatter validation.
# `curation: human` / `protected: true` не перезаписываются агентом без force.

append_wiki_log(operation: str, task_id: str = "",
                agent_id: str = "", message: str = "") -> dict

validate_wiki() -> dict
# Проверка frontmatter, sources, wikilinks и task refs.

lint_wiki(fix_index: bool = False) -> dict
# Wiki hygiene: orphans, stale pages, missing links, stale locks.

regenerate_wiki_index() -> dict
# Пересборка wiki/index.md.
```

#### PRD (4 tools)

```python
init_prd(task_id: str) -> dict
# создаёт prd/<id>.md по шаблону, заменяя <task-id>, <ts>, <Title>

commit_prd(task_id: str) -> dict
# парсит ## Subtasks, нормализует ID, заливает в active.md, статус -> committed

get_prd_status(task_id: str) -> dict
# {"prd_status": "draft|committed", "subtasks": [...], "total": N, "done": K}

read_prd(task_id: str) -> dict
# содержимое prd/<task_id>.md
```

#### Indexing (5 tools)

```python
rebuild_index(with_obsidian: bool = False) -> dict
# Полная пересборка всех JSON-файлов индекса и поискового движка.

index_status() -> dict
# Статус манифеста: дата, кол-во страниц, линков и документов.

search_brain(query: str, page_type: str = "", limit: int = 10) -> dict
# Полнотекстовый поиск BM25 с ранжированием и сниппетами.

get_backlinks(slug: str) -> dict
# Список всех страниц, ссылающихся на данную.

get_source_map(slug: str = "") -> dict
# Карта соответствия wiki-страниц и их raw-источников.
```

#### Raw (2 tools)

```python
add_raw_source(slug: str, content: str, title: str = "",
               url: str = "", source_type: str = "article",
               force: bool = False) -> dict
# Создаёт raw/<slug>.md с frontmatter; по умолчанию запрещает overwrite.

ingest_source(slug: str, content: str, title: str = "",
              url: str = "", source_type: str = "article",
              update_index: bool = True) -> dict
# Создаёт raw/<slug>.md и wiki/source-<slug>.md skeleton.
```

### Транспорт

stdio (стандартный для MCP). Сервер читает с stdin, пишет в stdout.
Стартует через `brain-mcp` без аргументов.

Запуск из других клиентов: команда `brain-mcp` (полный путь
`$HOME/.local/bin/brain-mcp`).

### Совместимость с CLI

MCP и shell **работают с одними файлами**. Можно:
- Делать `brain-task take` в терминале и параллельно вызывать
  `brain__add_council_opinion` из Claude Code — состояние согласовано.
- Локи общие. MCP-агент может перехватить stale-лок, оставленный
  shell-сессией.
- Git auto-commit работает в обоих режимах одинаково.

---


## Tmux-launcher

Подробно описан выше в [CLI-инструменты → brain-launch](#brain-launch--tmux-сессия-для-совета).

### Workflow примера

```bash
# Задача в active.md:
# - [ ] [P1] t-2026-05-01-tax-edge-case — Самозанятый-разработчик: можно?
#       role: tax-advisor   mode: council
#       council: [team:legal]

brain-launch t-2026-05-01-tax-edge-case --dry-run
# tmux session: brain-t-2026-05-01-tax-edge-case
# roles:
#   lawyer       →  claude
#     cmd: brain-run --role lawyer --task t-... --agent-id lawyer-tmux | claude
#   compliance   →  claude
#     cmd: brain-run --role compliance --task t-... --agent-id compliance-tmux | claude
#   paralegal    →  gemini
#     cmd: brain-run --role paralegal --task t-... --agent-id paralegal-tmux | gemini

brain-launch t-2026-05-01-tax-edge-case
# → tmux attach -t brain-t-2026-05-01-tax-edge-case
# → 3 окна с разными CLI работают параллельно

brain-launch t-2026-05-01-tax-edge-case --watch --dry-run
# Watch plan for session: brain-t-2026-05-01-tax-edge-case
#   Watching windows: lawyer, compliance, paralegal
#   Would poll: council/t-2026-05-01-tax-edge-case/ for opinion files
#   Would poll: .locks/ for lock status
#   Note: auto-complete is not enabled in this version.

brain-launch t-2026-05-01-tax-edge-case --watch
# Session: brain-t-2026-05-01-tax-edge-case
# Windows:
#   0: lawyer  [claude]
#   1: compliance  [claude]
#   2: paralegal  [gemini]
```

После завершения работы каждое окно ждёт нажатие клавиши перед закрытием
(чтобы можно было прочитать вывод).

### `--watch` режим

`brain-launch <task-id> --watch` позволяет проверить статус запущенной сессии:

- Если tmux не установлен: ошибка `tmux not found, install tmux to use --watch` (exit 1).
- Если сессия не существует: подсказка как запустить (exit 1).
- Если сессия есть: список окон и текущий процесс в каждом окне.

`brain-launch <task-id> --watch --dry-run` только печатает план наблюдения и завершается с кодом 0, не требует tmux.

---


## Git auto-commit

`~/brain/` инициализируется как git-репозиторий. Каждая мутирующая
операция делает локальный коммит с осмысленным сообщением:

```
init brain
task-add: t-2026-05-01-foo
task-start: t-2026-05-01-foo by claude-opus-7f3a
task-done: t-2026-05-01-foo by claude-opus-7f3a
council-start: t-2026-05-01-bar
council-opinion: t-2026-05-01-bar by lawyer/lawyer-7f3a
council-synth: t-2026-05-01-bar
prd-init: t-2026-05-01-baz
wiki: my-new-page
raw: source-from-2026
```

### Что коммитится

```
tasks/ wiki/ council/ raw/ doctrine/ prd/ roles/ teams/ MEMORY.md
```

### Что в .gitignore

```
.locks/                 # эфемерные блокировки
.agent-configs/         # симлинки наружу
.cli-mapping.sh         # личный конфиг с командами CLI
.brain/index/           # generated machine index cache
*.bak *.tmp *~ .DS_Store
```

### Опциональный remote

```bash
cd ~/brain
git remote add origin <your-private-repo>
git push -u origin main
```

После этого можно синхронизировать память между машинами.

### Откат

```bash
cd ~/brain
git log --oneline -20
git revert <commit>          # safe revert
git reset --hard HEAD~1      # destructive, осторожно
```

---


## Подключение CLI-агентов

### Глобальные симлинки

После `setup-brain-v2.sh`:

```
~/.claude/CLAUDE.md      → ~/brain/MEMORY.md
~/.codex/AGENTS.md       → ~/brain/MEMORY.md
~/.gemini/GEMINI.md      → ~/brain/MEMORY.md
```

Любой запуск Claude Code / Codex / Gemini CLI из любой директории
автоматически получит MEMORY.md как системный промпт.

### Per-project подключение

```bash
cd /path/to/project
brain-link
# создаёт ./CLAUDE.md, ./AGENTS.md, ./GEMINI.md, ./.cursorrules
# → симлинки на ~/brain/MEMORY.md
```

Per-project переопределяет глобальный (если CLI поддерживает оба).

### Через MCP

```bash
claude mcp add brain "$HOME/.local/bin/brain-mcp"
```

Tools `brain__*` становятся доступны во всех Claude Code сессиях.

### Optional: Obsidian skills

Brain wiki совместим с Obsidian vault-подходом. Для агентной работы с
Obsidian-спецификой можно поставить upstream skill-pack `kepano/obsidian-skills`
без vendoring кода в Brain:

```bash
bash install-obsidian-skills.sh
```

Ставятся skills:

| Skill | Когда использовать |
|---|---|
| `obsidian-markdown` | Правки `wiki/*.md`, frontmatter, wikilinks, callouts, embeds |
| `obsidian-bases` | Создание `.base` представлений для vault/dashboard |
| `json-canvas` | Создание `.canvas` карт, схем, roadmap/council maps |
| `obsidian-cli` | Работа с открытым Obsidian vault через `obsidian` CLI |
| `defuddle` | Очистка web-страниц в Markdown перед `brain-ingest` |

Правило приоритета не меняется: эти skills помогают редактировать формат
Obsidian, но не могут автоматически перезаписывать `curation: human` или
`protected: true` страницы.

После установки перезапусти Codex, чтобы skill registry перечитался.

Источник: `https://github.com/kepano/obsidian-skills`, лицензия MIT.

### Прямой запуск с собранным промптом

```bash
brain-run --role <role> --task <id> --agent-id <id> | <ваш CLI>
```

Это работает с любым CLI, который читает stdin. Не требует никакой
интеграции — просто pipe.

---


## Production Hardening (Phase 6)

### Webhook Reliability

`brain-task complete` доставляет событие `task-done` с retry/backoff и idempotency key:

- **Retries:** до `BRAIN_WEBHOOK_RETRIES` попыток (default 3) с задержкой 1→2→4 сек.
- **Idempotency key:** заголовок `X-Brain-Idempotency-Key` (UUID5 от task_id + timestamp). Позволяет endpoint-у дедуплицировать повторные доставки.
- **Dead-letter:** при окончательном провале — запись в `$BRAIN_PATH/.webhooks/dead-letter.jsonl`.
- **Replay:** `brain-task webhook-replay` — переотправить все записи из dead-letter против `BRAIN_WEBHOOK_URL` и очистить файл при успехе.

```bash
# Посмотреть очередь не доставленных событий
cat $BRAIN_PATH/.webhooks/dead-letter.jsonl

# Повторить доставку после восстановления провайдера
export BRAIN_WEBHOOK_URL=https://...
brain-task webhook-replay
# Expected: replayed=N remaining=0
```

### Learning Quality Controls

Перед активацией урока автоматически проверяются:

1. **Duplicate gate** — если уже есть active урок с эквивалентным правилом (по нормализованной сигнатуре), новый урок не активируется.
2. **Expiry filter** — уроки с полем `expires: YYYY-MM-DD` в прошлом пропускаются при prompt injection; `brain-learn prune-expired` переводит их в `deprecated`.
3. **Wiki conflict detection** — `brain-learn quality-check [--id ID]` проверяет, не противоречит ли правило урока human-curated странице wiki.

```bash
# Проверить конкретный урок
brain-learn quality-check --id les-20260504-abc12345

# Проверить все pending уроки
brain-learn quality-check

# Deprecate все просроченные active уроки
brain-learn prune-expired
```

### Release Gating

`brain-release check` запускает 5 gate-проверок перед тегированием:

1. `active=0` — нет открытых задач
2. `brain-lint` — нет orphaned страниц / stale locks
3. `brain-validate` — целостность wiki и контрактов курации
4. `tests/smoke.sh` — `ALL TESTS PASSED`
5. `index health=ok` — поисковый индекс актуален

```bash
brain-release check          # только проверка (safe, read-only)
brain-release tag v6         # check + создать тег (требует явного подтверждения)
brain-release tag v6 --yes   # без интерактивного confirm (для CI)
```

### Failover Drills

Три failover сценария описаны и верифицированы в `tests/e2e-failover.sh`:

| Drill | Сценарий | Ожидаемый результат |
|---|---|---|
| 1 — Stale-lock takeover | Агент A захватывает лок, TTL истекает | Агент B захватывает stale-лок автоматически |
| 2 — Dead-letter replay | Webhook недоступен при complete | dead-letter запись → replay после восстановления |
| 3 — Council partial | Один участник совета не отвечает | Синтез создаётся из доступных мнений |

```bash
bash tests/e2e-failover.sh   # прогнать все 3 drill'а
```

### Operational Metrics

`GET /api/metrics` в `brain-dashboard serve` возвращает flat JSON:

```json
{
  "generated_at": "2026-05-04T12:00:00Z",
  "orchestration": { "tasks_active": 0, "tasks_done": 41, "locks_active": 0, "locks_stale": 0, "councils_active": 0 },
  "learning":      { "incidents": 3, "lessons_pending": 1, "lessons_approved": 0, "lessons_active": 2, "lessons_deprecated": 0 },
  "webhook":       { "dead_letter_count": 0 },
  "policy":        { "status": "unchecked" }
}
```

---


## Установка

### Исходный код и Runtime
Система поставляется в виде набора скриптов и шаблонов. Исходные файлы расположены в:
- `runtime/bin/` — исполняемые инструменты (CLI).
- `runtime/templates/v2/` — статический контент для `setup-brain-v2.sh`.
- `runtime/mcp/server.py` — исходный код MCP-сервера.

Установочные скрипты копируют файлы из `runtime/` в `~/.local/bin/` и другие директории, используя `install -m 755`. `setup-brain-v2.sh` разворачивает базовую структуру памяти, загружая статический контент из `runtime/templates/v2`.

### Где запускать

Единственный вход — системный чекаут (`$BRAIN_SYSTEM_PATH`, этот репозиторий).
Установщики и `pyproject.toml` живут только там; копировать их в корень данных
(`$BRAIN_PATH`) нельзя. Из корня данных `SCRIPT_DIR` совпадает с `BRAIN`, setup
считает установку однокорневой, пересоздаёт `roles/`, `doctrine/`, `skills/`,
`config/` и перезаписывает операторский `MEMORY.md` шаблоном. `brain-validate`
и pre-commit write-path guard отклоняют такую копию, называя канонический файл.

### Порядок установки

Запустите по порядку, находясь в системном чекауте:

```bash
cd "$BRAIN_SYSTEM_PATH"
```

1. **Базовая установка:** `bash setup-brain-v2.sh`
   - Устанавливает `brain-common` и весь набор runtime CLI.
   - Загружает контент из `runtime/templates/v2`.
   - *Примечание:* Legacy v1 (`setup-brain.sh`, `runtime/templates/v1`, `brain-task-v1`) удалён в Phase 7.

2. **Legal + marketing:** `bash add-teams-brain.sh`
3. **PM + Finance:** `bash add-pm-finance-brain.sh`
4. **Designer + negotiator:** `bash add-design-negotiator-brain.sh`
5. **Doctrine + tax boundaries:** `bash refine-tax-boundaries.sh`
6. **Power features (PRD + tmux + git):** `bash add-power-features-brain.sh`
7. **Doctrine patching:** `bash patch-brain-run-doctrine.sh`
8. **MCP-сервер (опционально):** `bash install-brain-mcp.sh`
9. **Obsidian skills (опционально):** `bash install-obsidian-skills.sh`

### Проверка установки

Минимальная приемка после установки:

```bash
export PATH="$HOME/.local/bin:$PATH"
export BRAIN_PATH="${BRAIN_PATH:-$HOME/brain}"

cd "$BRAIN_SYSTEM_PATH"
bash setup-brain-v2.sh
bash install-brain-mcp.sh
codex mcp add brain "$HOME/.local/bin/brain-mcp"
codex mcp list

brain-index rebuild --with-obsidian
brain-index status
brain-search "brain" --limit 5
bash tests/smoke.sh
```

Ожидаемые признаки успеха:

- `codex mcp list` показывает сервер `brain` со статусом `enabled`.
- `install-brain-mcp.sh` импортирует `server.py` и показывает `42` registered tools.
- `brain-index rebuild --with-obsidian` создает `.brain/index/` и `wiki/_views/`.
- `brain-search` запускается без ошибок импорта `brain_index`.
- `tests/smoke.sh` завершается строкой `ALL TESTS PASSED`.

После `codex mcp add brain ...` текущую Codex-сессию нужно перезапустить:
MCP registry читается при старте процесса, поэтому новые `brain__...` tools
появятся только в следующей сессии.

### End-to-end smoke на данных

Минимальный рабочий сценарий:

```bash
brain-ingest --source note://smoke/e2e --title "Brain E2E Smoke" <<'EOF'
Brain E2E smoke проверяет raw ingest, wiki links, machine index, search и Obsidian export.
EOF

brain-index rebuild --with-obsidian
brain-search "smoke index" --limit 5
brain-index sources --json
brain-validate
```

Этот сценарий должен оставить исходник в `raw/`, обновить машинный индекс,
вернуть результат поиска и пересобрать Obsidian views. Raw-файлы считаются
immutable: ручные правки делаются в `wiki/`, а не поверх исходника.

---


## Тестирование

Для проверки целостности системы используется скрипт `tests/smoke.sh`. Он выполняет следующие проверки:

- **Isolated v1 setup:** корректность установки базовых компонентов v1.
- **v2 stack:** полная проверка всех компонентов версии 2.x.
- **Права доступа:** наличие executable bit у всех CLI-инструментов.
- **Синтаксис:** проверка bash-скриптов и Python-кода (MCP) на отсутствие ошибок.
- **Rollback:** проверка отката при отсутствии обязательных задач.
- **Dry-run:** запуск `brain-launch` в тестовом режиме.
- **PRD commit:** валидация декомпозиции и записи сабтасков.
- **Doctrine:** проверка корректности подгрузки доктрин в промпт.

Запуск тестов:
```bash
bash tests/smoke.sh
```

---


## Архитектурные решения

### Почему файлы, а не БД

- Любой агент с filesystem-доступом работает без специальных адаптеров.
- Можно открыть как Obsidian vault, читать в редакторе, грепать.
- Git как версионирование — бесплатно.
- Backup = `tar -czf brain-backup.tar.gz ~/brain/`.

### Почему mkdir для блокировок

- Атомарность гарантирована POSIX.
- Не нужны зависимости (sqlite, redis).
- TTL даёт устойчивость к падениям.

### Почему 4 этапа налогов отдельно

Эмпирическое наблюдение: налоговые конфликты ролей всегда сводились к
вопросу «это считаем налог или ведём учёт» / «это договор или процесс» /
«это норма или отчётность». 4-этапная модель режет задачу так, что
вопроса больше не возникает.

### Почему roles + teams (не вместо)

- Роли — атомарные personas с явной ответственностью.
- Команды — алиасы для частых сочетаний.
- Без teams приходилось бы выписывать 3 роли каждый раз для legal-вопросов.
- С teams можно смешивать: `[team:legal, growth-analyst]`.

### Почему доктрина отдельный слой

Roles описывают **одну сторону** (что я делаю / что не делаю).
Doctrine описывает **стык** (как роль А и роль Б распределяют ответственность).
Это разные жанры документов, и разделение упрощает поддержку: добавление
новой роли не требует переписывать доктрину; уточнение стыка не требует
лазить во все role-файлы.

### Почему MCP опционален

- Не все CLI-агенты поддерживают MCP.
- Shell-CLI достаточен для всех use-cases.
- MCP даёт удобство (типизация, без shell-парсинга), но не новые возможности.

### Почему диверсификация моделей

Эмпирически — модели одного провайдера делают коррелированные ошибки
(одинаковая обучающая дистрибуция → одинаковые слепые пятна). Reviewer
другим провайдером ловит то, что developer не видит. Arbiter ещё одним —
чтобы не унаследовать слепые пятна обоих.

### Почему append-only лог

- Никто не теряется (race-condition безопасен для добавления).
- Полный аудит всех операций.
- Можно восстановить состояние перебором лога если файлы повреждены.

---


## Известные ограничения

### Concurrency

- `wiki/<page>.md` — гонка двух одновременных правок одной страницы
  возможна. На практике редко: страницы редактируют в разных контекстах.
  Митигация: культура «по одной странице обычно правит одна роль».
- `tasks/active.md` — большие правки (PRD commit) могут гоняться с
  параллельным take_task. На практике редко.

### Масштаб

- Система рассчитана на одного пользователя с 1-5 параллельными
  агентскими сессиями.
- Очередь задач до ~500 строк в active.md работает быстро.
- Wiki до ~1000 страниц поддерживается.
- Дальше — нужна замена `search_wiki` (сейчас grep) на векторный поиск
  (qmd / lancedb / chromadb).

### Безопасность

- Любой процесс с доступом к `~/brain/` может всё.
- Локи не проверяют криптографически — agent_id можно подделать.
  Но: модель угроз — это собственные агенты пользователя, не злоумышленники.
- `.cli-mapping.sh` может содержать API-ключи в env-переменных. В
  .gitignore. Но при пуше всего brain в remote стоит проверить.

### Wiki-search

- `search_wiki` сейчас — naive grep по содержимому. Точность низкая
  для синонимов, парафразов.
- Plan: интеграция с qmd (BM25 + векторный + LLM-rerank) или MCP-сервером
  типа `mcp-server-qdrant`.

### Доктрина

- Сейчас 2 doctrine-файла. По мере роста системы появятся ещё —
  `architect-vs-developer`, `pm-vs-product`, `cfo-vs-strategist`.
- Автоподгрузка работает по grep ссылок — если doctrine не упомянута в
  role-файле, в промпт не попадёт. Нужно явно ссылаться.

---


## Roadmap

### Current baseline (post-Phase 25, latest release tag: v23.1)

Implemented and covered by smoke tests:

- Core file-based Brain runtime: tasks, locks, roles, teams, doctrine, wiki,
  raw sources, PRD workflow and council workflow.
- MCP server, dashboard HTTP/SSE/API, write actions, audit log and metrics.
- `brain-launch`, `brain-handoff`, `brain-orchestrator` and provider health
  cache for multi-CLI execution and limit handoff.
- Learning loop with bounded lesson injection and local-only evidence storage.
- Token economy tools: compactors, adapters and dashboard token metrics.
- BM25 search, optional vector search, hybrid search and graph export.
- Universal skills, JIT skill injection, skill-aware routing, autonomous curator
  proposals and model fleet reporting.
- Federation preflight, safe import/proposal workflow, git sync, task merge and
  federated lock conflict checks.
- Operator console workflow: `brain-orchestrator console`, prompt artifacts under
  `.brain/orchestrator/prompts/`, visible terminal/log-tail support, dashboard
  operator panel and screenshot-based dashboard regression checks.
- Automation/QoL layer: `brain-ops refresh/watch`, periodic ops refresh from
  `brain-launch --watch`, sequential-by-default council automation with optional
  parallel mode, `brain-prd auto-breakdown`, and local CI/pre-commit scaffolding.
- Consolidated live Brain layout: root `roles/`, `teams/`, `doctrine/`, `wiki/`,
  `raw/`, `tasks/`, `skills/` and `provider-matrix` are canonical in the
  repository; `runtime/templates/` are fallback templates.
- Repository hygiene baseline: generated caches, IDE state and local policy
  directories are excluded from git history; generated `.brain/` content remains
  cache/operator state, not source.

### Near term (hours)

- Re-establish a clean release baseline after repository history cleanup:
  `brain-validate`, `brain-lint`, `brain-index rebuild`, `brain-release check`
  and smoke tests must be green before the next tag.
- Normalize the intentionally cleared active queue: keep the short empty queue
  format if accepted by the parser, or restore the canonical headers if release
  gates require them.
- Define the folder-native workspace protocol before adding more orchestration:
  each important work folder may contain `BRAIN.md`, `TASKS.md` and `LOG.md`;
  the folder remains the source of truth.
- Do not introduce a manually maintained central project registry. Any global
  overview must be generated by scanning filesystem markers, not edited as a
  second source of truth.
- Convert this roadmap into the next PRD/ticket batch only after the live vault
  is green, so new work does not hide release drift.

### Phase 26 - Folder-native Workspaces

- Make self-describing folders the unit of work for agents. A folder can opt in
  by adding `BRAIN.md` with purpose, local rules, allowed roles, sensitive zones
  and completion checks.
- Support optional folder-local `TASKS.md` and `LOG.md` so document development,
  legal support and project coordination can live next to the actual files.
- Add read-only discovery that finds workspace folders by scanning for `BRAIN.md`
  under approved roots. Discovery output is generated cache/operator state, not a
  central registry to maintain by hand.
- Add a narrow launch path: user can point Brain at a folder, the agent reads the
  nearest `BRAIN.md`, chooses the right role, respects local write rules, and
  records substantial actions in the local log.
- Keep migration conservative: first inventory and describe existing folders,
  then introduce `_inbox/`, `_work/`, `_final/`, `_archive/` only where a folder
  actually benefits from that structure.
- Acceptance: an agent can work safely in at least three existing folders with
  folder-local instructions and tasks, without moving files or relying on a
  central project registry.

### Phase 27 - Workspace-aware Operator Console

- Make dashboard the primary operator shell for folder work, not just task
  monitoring: discovered workspaces, active local tasks, current agent run,
  prompt artifact, log tail, handoff state and release gates should be visible
  in one workflow.
- Add an explicit "launch visible orchestrator in this folder" path from the
  dashboard that uses existing `brain-orchestrator console` primitives and
  passes the selected folder as working context.
- Keep manual input support: long-running CLI sessions must remain visible and
  interactive while still writing bounded logs for agent inspection.
- Acceptance: operator can choose a workspace folder, launch a visible run,
  inspect the active log, and complete/handoff without copying terminal output
  by hand.

### Phase 28 - Reliability and Release Engineering

- Improve `brain-release` diagnostics so a repeated internal smoke failure
  reports the failing case, command, exit code and useful excerpt instead of a
  weak tail dump.
- Make release checks deterministic across clean installs, consolidated live
  repos and generated-cache states.
- Keep CI parity with local smoke tests and document any optional-dependency
  skips, especially vector search and browser/visual checks.
- Add regression coverage for task schema normalization, generated artifact
  ignores, and release-tag workflows after history rewrites.
- Acceptance: a failed release gate is actionable from its own output, and a
  passing release gate is enough to tag without repeating manual smoke runs.

### Phase 29 - Skill Curator Governance

- Harden the lifecycle from `proposal` -> `review` -> `install` -> `mount`.
- Suppress synthetic/noisy missing-skill tasks before they pollute the queue.
- Require human approval and security review for high-impact skills, tools with
  broad filesystem/network access, and provider-specific config rewrites.
- Add duplicate detection, version pinning, rollback metadata and role-specific
  acceptance checks.
- Acceptance: curator output is actionable, deduplicated and safe to review;
  no skill is mounted into a role without an auditable approval path.

### Later / optional

- Additional roles: `hr/people`, `data-engineer`, `investor-relations`.
- Stronger storage/search backend for larger vaults: SQLite FTS5, Tantivy,
  LanceDB or another local index depending on scale and portability needs.
- Universal Skill Compiler: translate external skill manifests between
  provider-specific formats such as `gemini-extension.json` and
  `.claude-plugin/marketplace.json`, replacing the current routing-only bridge.
- Federation beyond a single user's machines. Keep existing federation sync for
  personal environments, but defer multi-user governance until there is a real
  collaborative use case.
- Product-specific verticals. Brain may manage external work folders, but those
  folders should not redefine the runtime roadmap or create a central portfolio
  layer by default.

---


## Learning Loop (Phase 5)

### Обзор

Learning Loop — управляемая система накопления уроков из ошибок агентов.
Она НЕ является fine-tuning моделей и НЕ перезаписывает `roles/*.md` автоматически.
Это governed memory loop с явным ревью, bounded prompt injection и человеческим/arbiter
контролем над высокорисковыми уроками.

### Локальная память (Local-Memory Policy)

Данные обучения хранятся локально в `$BRAIN_PATH/learning/` и **не хранятся в git**.
Код алгоритмов и CLI хранится в git (`runtime/bin/brain-learn`, `runtime/lib/brain_learning.py`).

```text
$BRAIN_PATH/
└── learning/
    ├── incidents/        ← полные доказательства ошибок (НИКОГДА не в prompt)
    ├── lessons/
    │   ├── pending/      ← кандидаты на урок, ждут ревью
    │   ├── active/       ← одобренные уроки, доступны для injection
    │   └── deprecated/   ← устаревшие уроки
    └── summaries/        ← краткие сводки по ролям (developer.md, reviewer.md, ...)
```

### Формат incident

```yaml
---
id: inc-<YYYYMMDD>-<hash8>
source: human-edit | human-review | test-failure | smoke-failure |
        lint-failure | validate-failure | runtime-error | ci-failure | static-analysis
task_id: <task-id>
role: developer | reviewer | architect | ...
model: <model-name>
agent_id: <agent-id>
severity: low | medium | high
created: <ISO date>
tags: []
---

## Evidence
<полные логи, diff, или текст правки>

## Root Cause
<анализ причины — может дополняться после исправления>

## Fix
<что было исправлено — может дополняться после исправления>
```

### Формат lesson (pending/active/deprecated)

```yaml
---
id: les-<YYYYMMDD>-<hash8>
incident_id: inc-<...>
status: pending | approved | active | rejected | deprecated
severity: low | medium | high
roles: [developer]          ← список ролей, для которых урок релевантен
tags: [http-proxy, testing]
created: <ISO date>
updated: <ISO date>
approved_by: <agent-id | "arbiter">
---

## Rule
<одна чёткая правило, ≤ 2 предложения>

## Context
<когда применять этот урок>
```

### Lifecycle уроков

```text
incident → pending → approved → active → deprecated
                  ↘ rejected
```

Переходы:
- `brain-learn capture` → создаёт incident + pending lesson
- `brain-learn approve <id>` → pending → approved (только low/medium severity)
- `brain-learn activate <id>` → approved → active
- `brain-learn reject <id>` → pending → rejected (выводится из цикла)
- `brain-learn deprecate <id>` → active → deprecated

**High-severity gate:** pending(high) уроки требуют явного одобрения роли `arbiter`
перед тем как стать active. Команда `brain-learn activate <id>` для high-severity
без arbiter approval завершится с ошибкой.

```text
pending(high) → brain-learn approve <id> --as arbiter → approved → active
```

### Источники incidents

| Source | Когда создаётся |
|---|---|
| `human-edit` | Человек вручную отредактировал output агента |
| `human-review` | Человек оставил ревью с замечаниями |
| `test-failure` | Unit/integration тест упал |
| `smoke-failure` | `bash tests/smoke.sh` вернул ошибку |
| `lint-failure` | `brain-lint` нашёл нарушение |
| `validate-failure` | `brain-validate` нашёл нарушение |
| `runtime-error` | Ошибка во время выполнения CLI/MCP |
| `ci-failure` | CI pipeline упал |
| `static-analysis` | Статический анализатор нашёл проблему |

### Prompt Injection Policy

`brain-run` инжектирует bounded блок перед системным промптом роли:

```text
# === LEARNED LESSONS ===
Top relevant lessons for role=<role>:
1. [les-...] <Rule text>
2. [les-...] <Rule text>
```

Правила выборки (в порядке приоритета):
1. `roles` содержит текущую роль
2. `tags` пересекаются с контекстом задачи
3. `severity` — высокий severity выше
4. Свежие (`created`) уроки выше старых
5. Уроки с высоким `repetition_count` (многократно встреченная проблема) выше

Жёсткие лимиты:
- **max_lessons: 5** — не более 5 уроков за раз
- **max_tokens: 800** — суммарный бюджет текста уроков
- **incidents не читаются** — только `lessons/active/` попадают в prompt
- **deprecated уроки исключены**

### Human Correction Priority

При конфликте данных приоритет:
1. **Human correction** (самый высокий)
2. Source material (raw/)
3. Agent output

Если incident создан через `--source human-edit`, его rule автоматически
получает приоритетный флаг и применяется первым при ранжировании.

### High-Severity Approval Protocol

Если `brain-learn capture` создаёт урок с `severity: high`:
1. Урок попадает в `lessons/pending/` со статусом `pending`
2. `brain-learn list --pending` показывает его с меткой `[HIGH - arbiter required]`
3. Только `brain-learn approve <id> --as <arbiter-agent-id>` (роль `arbiter`) меняет на `approved`
4. Попытка `brain-learn activate <id>` без arbiter approval → ошибка с подсказкой

### Automatic Phase Capture

После каждой фазы можно запустить:

```bash
brain-learn phase-capture --phase <phase-id>
```

Команда анализирует:
- Git diff с baseline тега фазы
- Коммиты с ключевыми словами: `fix`, `smoke`, `lint`, `validate`, `proxy`, `failure`
- Изменённые файлы `$BRAIN_PATH/` (wiki-правки человека)

Создаёт incidents и pending lessons. **Не активирует уроки автоматически.**

---


## Cheat sheet

### Команды на каждый день

```bash
# СМОТРЕТЬ
brain-task                          # вся очередь
brain-task next                     # следующая задача
brain-task next --role developer    # следующая для разработчика
brain-task show <id>                # подробности задачи
brain-task deps <id>                # граф зависимостей
brain-task log 20                   # последние 20 операций
brain-council teams                 # все команды
brain-prd list                      # все PRD
brain-status                      # статус оркестрации (read-only)

# ДОБАВЛЯТЬ
brain-task add "<text>" --role R --prio P1
brain-prd init <task-id>            # PRD по шаблону
brain-council start <task-id>       # совет

# РАБОТАТЬ
brain-task take <id> --as <agent>           # взять (auto-lock)
brain-task complete <id> --as <agent>       # завершить (auto-release + git)
brain-task release <id> --as <agent>        # отказаться
brain-task block <id> "<reason>"

# ЗАПУСКАТЬ АГЕНТА
brain-run --role R --task <id> --agent-id <id> | <CLI>
brain-launch <id>                   # tmux с советом
brain-launch <id> --dry-run         # посмотреть что запустится

# СЛУЖЕБНОЕ
brain-lock status                   # все локи
brain-lock cleanup                  # удалить stale
brain-link                          # подключить к проекту
```

### Pattern «параллельная работа двух моделей»

```bash
# Задача:
# - [ ] [P1] t-foo — Реализовать X
#       role: developer    mode: solo

# Терминал 1: developer на claude
DEV="dev-$(uuidgen | head -c 4)"
brain-task take t-foo --as $DEV
brain-run --role developer --task t-foo --agent-id $DEV | claude
brain-task complete t-foo --as $DEV

# Терминал 2: reviewer на gemini (наблюдает, не take)
REV="rev-$(uuidgen | head -c 4)"
brain-run --role reviewer --task t-foo --agent-id $REV | gemini
```

### Pattern «совет на стыке зон»

```bash
# Задача:
# - [ ] [P1] t-bar — Можно ли нанять X как самозанятого?
#       role: tax-advisor    mode: council
#       council: [tax-advisor, lawyer]

brain-launch t-bar                   # tmux: 2 окна, разные CLI

# После того как обе роли отписались:
brain-council status t-bar
brain-council synthesize t-bar
brain-run --role arbiter --task t-bar --council | claude
```

### Pattern «крупный проект через PRD»

```bash
# 1. Создать parent
brain-task add "Запуск нового продукта" --role architect --mode prd

# 2. Архитектор делает PRD
brain-prd init <parent-id>
# заполнить ~/brain/prd/<parent-id>.md
brain-prd commit <parent-id>

# 3. Тикеты разлетаются по ролям, deps работают
brain-task next --role architect    # сначала архитектурные
# ... выполнили
brain-task next --role developer    # потом разработка
# ... и т.д.
brain-prd status <parent-id>        # прогресс
```

---


## Матрица решений

### Когда какой режим выбрать

| Ситуация | Mode | Кому отдать |
|---|---|---|
| Тикет атомарный, ясно что делать | `solo` | конкретная роль |
| Два видения, как делать | `council` | 2-3 роли |
| Крупная работа, надо декомпозировать | `prd` | architect |
| Разногласия после council | новая `solo` для arbiter | arbiter |

### Когда какой совет

| Тип вопроса | Council |
|---|---|
| Архитектурное решение с trade-offs | `[team:engineering]` |
| Ревью договора с регуляторными требованиями | `[team:legal]` |
| Запуск контента / лендинга | `[team:creative, growth-analyst]` |
| Выбор юр.формы | `[team:finance, lawyer]` |
| Переговоры по крупной сделке | `[team:negotiation]` |
| Налоговый вопрос с договорной частью | `[tax-advisor, lawyer]` |
| Налоговый вопрос с регуляторкой (ФЗ-152, AML) | `[tax-advisor, compliance, lawyer]` |
| Запуск продукта (продукт + финансы + право) | `[product, cfo, lawyer, strategist]` |
| Quarterly retro проекта | `[team:pm]` |
| Анализ конкурентов / рынок | `[team:research]` |
| Структурирование международной сделки | `[tax-advisor, lawyer, compliance, cfo]` |

### Когда какую модель

| Роль | Дефолт | Альтернатива | Почему |
|---|---|---|---|
| architect | claude-opus | gpt-5 / o3 | мощность для нюансов |
| developer | claude-sonnet | gpt-4o | быстрая, точная |
| reviewer | gemini-pro | gpt-4o | **другой провайдер** |
| arbiter | claude-opus | gpt-5 | **отличный от участников** |
| linter | gpt-4o-mini | gemini-flash | дешёвая, рутина |
| paralegal | gemini-flash | gpt-4o-mini | дешёвая + web |
| researcher | claude (web_search) | perplexity | нужен web |
| growth-analyst | claude-opus + Python | gpt-5 + code | code execution |
| остальные мощные | claude-opus | gpt-5 | мощность |

### Решение «escalate или нет»

| Симптом | Действие |
|---|---|
| Задача в одной зоне, ясно что делать | `solo` с primary |
| Задача затрагивает 2 зоны | `council` с обеими ролями |
| Задача затрагивает 3+ зон | `council` с командой(ами) |
| После работы возникло знание | страница в `wiki/` |
| После работы возникли новые задачи | заводи `- [ ]` с deps |
| После council есть разногласия | arbiter синтезирует |
| arbiter не уверен | новая researcher-задача с указанием неопределённости |
| Тикет старше месяца без движения | linter маркирует, либо block, либо kill |

---


## Глоссарий

| Термин | Определение |
|---|---|
| **Agent** | Одна сессия LLM. Имеет agent_id для идентификации в логах и локах. |
| **Role** | Persona-файл, определяющий рамки работы агента. |
| **Team** | Именованный набор ролей для использования в режиме `council`. |
| **Council** | Режим задачи, где несколько ролей дают независимые мнения, arbiter синтезирует. |
| **Doctrine** | Документ, описывающий разграничение между двумя+ ролями. |
| **PRD** | Product Requirements Document. Декомпозиция крупной задачи на сабтаски. |
| **Lock** | Блокировка задачи, предотвращающая гонку нескольких агентов. |
| **Stale lock** | Лок с истёкшим TTL. Может быть перехвачен другим агентом. |
| **Arbiter** | Роль, синтезирующая мнения совета в финальное решение. |
| **Wiki** | Накапливаемое знание агентов. Persistent memory между сессиями. |
| **Raw** | Исходные источники (immutable). Не редактируются после ingest. |
| **MCP** | Model Context Protocol — стандарт интеграции tools в LLM-агенты. |
| **BATNA** | Best Alternative To Negotiated Agreement. Используется в роли negotiator. |
| **DoD** | Definition of Done. Используется в роли delivery. |
| **ADR** | Architecture Decision Record. Создаётся ролью architect. |

---


## Лицензия и атрибуция

Концепция [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) (Andrej Karpathy) — основа подхода к persistent memory.
Идея ролевой работы и phase-machine вдохновлена [pickle-rick-claude](https://github.com/gregorydickson/pickle-rick-claude).

Сама система — кастомная разработка, без внешней лицензии (личное использование).
