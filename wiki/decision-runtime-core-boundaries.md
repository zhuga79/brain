---
title: Decision — Runtime Core: границы модулей и единый владелец очереди
type: decision
created: 2026-08-10
updated: 2026-08-10
curation: agent
protected: false
source_policy: advisory
tags: [decision, architecture, runtime, tasks, concurrency]
sources: []
related: [about-brain, architecture-overview, decision-llm-stack, decision-role-model-routing, decisions-log, workflow-solo-council]
visibility: public
---

# Decision: Runtime Core — границы модулей и единый владелец очереди

**Статус:** предложено
**Задача:** `t-2026-08-10-brain-runtime-48-12k-loc-49-c`
**Роль:** architect (`operator-architect-1112723` → `operator-architect-1119019` по handoff)

## Контекст (что измерено)

| Слой | Объём |
|------|-------|
| `runtime/bin/` | 49 файлов, 13 104 LOC (33 python, 15 bash, 1 sh) |
| `runtime/lib/` | 38 модулей, 10 692 LOC (пакеты `brain_dashboard`, `brain_wiki`, `brain_federation`) |
| `runtime/mcp/` | 10 модулей, 1 278 LOC |
| `tests/` | 18 127 LOC, преимущественно shell-кейсы (`tests/cases/*.sh`) |

Крупнейшие файлы: `brain_dashboard/render/html.py` — 2333, `brain-dashboard` — 1206,
`brain_dashboard/data.py` — 948, `brain-orchestrator` — 912, `brain_index.py` — 841,
`brain-handoff` — 800. Собственное правило проекта — 200–400 LOC типично, 800 максимум —
нарушено в шести местах.

## Решение

Ввести трёхслойную структуру с **одним владельцем записи на каждый файл состояния** и
свести все существующие CLI/адаптеры к тонким фасадам над ней.

```
runtime/
├── brain_core/          # домен, без I/O-побочек кроме своих файлов
│   ├── paths.py         # brain_path(), ACTIVE/DONE/LOG/LOCKS
│   ├── clock.py         # utc_now(), iso()
│   ├── atomic.py        # read_text/write_text (tmp+fsync+os.replace), flock
│   ├── journal.py       # log_op(), git_commit()
│   ├── taskfile.py      # ЕДИНСТВЕННЫЙ писатель active.md/done.md
│   ├── grammar.py       # regex блока задачи — единственная копия
│   └── locks.py         # acquire/release/refresh, атомарный stale-reclaim
├── brain_app/           # сценарии
│   ├── queue.py         # take/release/complete/block/add/next/list/deps
│   ├── council.py  wiki.py  index.py
│   ├── orchestration.py # run/console/fallback
│   └── cycles/          # общий runner: dry-run|apply|json|systemd|corrective
├── brain_cli/           # argparse-фасады, ≤80 LOC каждый
├── mcp/                 # адаптер поверх brain_app
└── ui/                  # dashboard: render отдельно от data
```

Правила границ:

1. **Никто, кроме `brain_core.taskfile`, не открывает `active.md`/`done.md` на запись.**
   Сейчас это делают 4 инлайн-heredoc'а в `brain-task` (`take`/`release`/`complete`/`block`),
   `mcp/tools_tasks` (`add_task` через `open("a")`, `block_task` через `write_text`),
   `brain-queue-cycle:226`, `brain-review-cycle:338` и `brain-validate-cycle:43`.
   (`brain_federation/plan.py` `active.md` только читает — записи там нет.)
2. **Одна грамматика задачи.** `brain_core.grammar` — единственное место с regex блока.
3. **Bash остаётся только там, где нужен процесс/tmux** (`brain-orchestrator console`,
   `launch-dashboard.sh`). Вся логика — Python. `python3 - <<'PY'` внутри bash запрещён.
4. **`runtime/lib` устанавливается как пакет** (`pip install --user -e`), а не копируется
   `cp -R`. `sys.path.insert` исчезает из 27 файлов.
5. **Слой данных (`wiki/ tasks/ council/ raw/ doctrine/ roles/`) читается только через
   `brain_core`/`brain_app`.** UI, MCP и cycles не парсят markdown сами.

## Обоснование

### Что сломано сегодня — по приоритетам

**P0 — потеря данных при штатном сценарии параллельной работы**

`brain-task take|release|complete|block` мутируют `active.md` через
`open(path, "w").write(new)` — неатомарно и без файлового лока. Лок-протокол
(`.locks/<task-id>/owner`) защищает **задачу**, но не **файл**. Два агента, работающие
над *разными* задачами — ровно тот сценарий, ради которого лок-протокол и написан, —
дают lost update: тот, кто пишет вторым, затирает чужую правку целиком.
Атомарная запись в системе уже реализована — `brain_launch_queue.py:65` и
`brain_federation/plan.py:422` (tmp + fsync + `os.replace`), но на очередь задач она
не распространена.

**P0 — гонка в самом примитиве блокировки**

`brain-lock:60-63`: при обнаружении stale-лока выполняется `rm -rf "$dir"; mkdir "$dir"`
без проверки кода возврата `mkdir`. Два агента, одновременно увидевшие протухший лок,
оба получают `ok` и оба считают себя владельцами. Захват свободного лока (`mkdir` с
проверкой) корректен — сломан именно путь перехвата.

**P0 — грамматика задачи разошлась между читателем и писателем**

`brain_task_parser.TASK_HEAD_RE` требует `\[P[0123]\]`. Писатели используют другое:
`take` — `\[\w+\]`, `block` — `\[\w*\]`, `complete` — `[~ x]` в позиции состояния,
`take` — только `' '`. Задача, записанная с приоритетом вне `P0..P3` (или с состоянием,
которое допускает один regex и не допускает другой), успешно пишется, но невидима для
`brain-task next`, дашборда, индекса и MCP. Комментарий «Single source of truth» в
`brain_task_parser.py` описывает намерение, а не факт: он верен для чтения, но не для записи.

**P1 — нет доменного ядра, есть копипаст**

Измерено по `runtime/bin/`: `def brain_path` — 14 копий, `def utc_now` — 5,
`def read_text`/`write_text` — по 2–3, `slugify`/`iso` — по 2. Логика установки
systemd-юнитов (шаблоны `[Unit]`/`[Timer]` + инсталлятор) продублирована в 6 файлах:
`brain-provider-probe`, `brain-queue-cycle`, `brain-index-refresh`, `brain-review-cycle`,
`brain-validate-cycle`, `brain-sync-cycle`; седьмая точка — `brain-dashboard:711`, который
эти же юниты запускает по HTTP. Создание corrective-задачи продублировано в 4.
Отдельный срез того же явления: 21 CLI из 48 не импортируют `runtime/lib` вообще
(≈3,5k LOC, крупнейшие — `brain-vector` 399, `brain-provider-probe` 367, `brain-release` 313,
`brain-council` 298) — этот код не покрыт ни одним из 37 python-тестов. `git_commit` и запись в `log.md`
существуют в трёх независимых реализациях: `brain-common` (bash), `mcp/common.py`,
`brain-task`. Четыре `*-cycle` скрипта — структурные близнецы с одинаковым прологом
`utc_now/iso/brain_path/read_text/write_text/parse_tasks/slugify`.

**P1 — четыре фасада над одним контрактом очереди**

`brain-task` (bash+heredoc), `brain-shell` (Python-обёртка, переопределяет
status/next/take/release/complete), `mcp/tools_tasks` (свой `add_task`/`block_task`
с записью), `brain-dashboard`/`brain-orchestrator console`. Каждое изменение контракта
очереди требует четырёх согласованных правок; на практике они расходятся — см. P0-грамматику.

**P1 — bash↔python шов как позиционный ABI (снято)**

Позиционный модуль `brain_task_next` удалён. `brain-task` зовёт именованный
интерфейс `brain_app.queue` (`next`/`list`/`show`/`deps`/`add` с `--role`,
`--surface`, `--json`). Bootstrap `sys.path` больше не передаётся седьмым
аргументом. Остаточный риск — version skew установленной и репозиторной копии
при `install -m 755` + `cp -R` в `setup-brain-v2.sh`; приоритет путей в
`brain_lib_loader.ensure_lib()` и в `mcp/common.py` по-прежнему разный.

**P1 — неограниченный конкурентный ребилд индекса**

Каждая мутация в `brain-task` (add/take/release/complete/block) запускает
`brain-index rebuild >/dev/null 2>&1 &`. Пять быстрых операций — пять параллельных
процессов, пишущих в `.brain/index/` через `brain_wiki.write_text` без атомарности
и без взаимного исключения. Индекс и BM25-кэш могут остаться в полусобранном виде,
а `brain-search` — молча вернуть неполный результат.

**P2 — роли и доктрины не имеют машинного контракта**

`brain-run:227` привязывает доктрину к роли грепом текста: `grep -oE 'doctrine/[a-z0-9._-]+\.md'`
по прозе `roles/<role>.md`. Упоминание доктрины в любом контексте — включая «эту доктрину
читать не нужно» — подгрузит её в промпт. При этом `teams/*.md` frontmatter имеют
(`roles: [architect, developer, reviewer]`, `curation: human`), а `roles/*.md` — нет.
Escalation matrix (зона → primary → escalate) существует только как таблица в прозе
`MEMORY.md` и её копии в `runtime/templates/v2/MEMORY.md`: она не исполняется, не
валидируется и расходится с реальностью бесшумно.

**P2 — размер модулей**

`brain_dashboard/render/html.py` (2333 LOC) и `data.py` (948) — единственная причина,
по которой дашборд считается «связанным» с `brain_wiki`/`brain_index`/`brain_provider`/
`brain_workspace`: он импортирует пять доменных модулей и дополнительно шеллаутит
(`data.py:670`). Направление зависимостей само по себе верное (UI сверху), проблема —
в объёме и в том, что рендер и сбор данных живут в одном пакете без контракта между ними.

**P1 — три источника истины для маршрутизации «роль → модель»**

Роутинг задан одновременно в трёх местах, и сегодня они расходятся:
`.cli-mapping.sh` (bash-строки `cli_for_<role>`, читается `brain-common`/`brain-run`/`brain-launch`),
`wiki/provider-matrix.json` (читается `brain_provider`, `brain-orchestrator`, дашбордом,
`brain-handoff`) и проза `[[decision-llm-stack]]`. На момент ревью `decision-llm-stack`
и матрица называли для `architect` codex 5.5, `.cli-mapping.sh` — `claude --model opus`
с пометкой «квота исчерпана». Это не гипотетический риск: именно на этом расхождении
данная задача получила `fallback_reason: quota_exceeded` и была передана по handoff.
Второй разрыв того же шва: `roles/` содержит 28 ролей, `provider-matrix.json` — 9;
19 ролей (весь legal/finance/marketing/PM-блок) не имеют записи о провайдере и молча
уходят в `CLI_DEFAULT`. Матрица при этом лежит в `wiki/` — конфиг исполнения внутри
слоя знаний, который курирует человек.

**P2 — стоимость сборки промпта не ограничена**

`brain-run` для этой задачи выдаёт 28,9 КБ, из них 20,8 КБ — `MEMORY.md` целиком (72%).
`MEMORY.md` совмещает конституцию, реестр ролей, реестр команд, escalation matrix и
индекс доктрин, поэтому растёт при добавлении любой роли — и цену платит каждый запуск
каждого агента, независимо от роли. Роль (`roles/architect.md`) — 1,5 КБ, то есть
собственно персона занимает 5% промпта.

**P2 — контракт CLI не идемпотентен и не проверяет владельца**

`brain-task take <id> --as <me>` возвращает exit 1, если лок уже принадлежит **мне**
(проверено в ходе ревью): `take` безусловно вызывает `brain-lock acquire`, а тот не
различает «занято другим» и «уже моё». Штатный сценарий «взял лок вручную по протоколу
из MEMORY.md, затем позвал `brain-task take`» ломается. Симметрично:
`brain-lock release <id>` без `--as` снимает **любой** лок, и `brain-task complete <id>`
без `--as` вызывает его именно так — завершение одной задачи может снять чужой лок.

**P2 — дашборд как неверсионированный control plane**

`brain-dashboard` (1206 LOC в `bin/`, обработчики inline во вложенном классе) — HTTP-сервер
с `do_POST`, который выполняет действия через `subprocess` над теми же CLI. Это делает
stdout и коды возврата CLI фактическим API между процессами, но нигде не зафиксировано
как контракт и не версионируется; 18k LOC shell-кейсов — единственное, что его удерживает.

### Эмпирическое подтверждение P0

Во время самого ревью три агента (предыдущий architect, его orchestrator-fallback и
параллельная сессия) одновременно писали `tasks/active.md`, `.cli-mapping.sh`,
`runtime/bin/brain-orchestrator` и эту страницу. Лок-протокол при этом отработал штатно
на уровне задачи, но не помешал конкурентной записи в общие файлы — ровно тот разрыв
между «лок на задачу» и «лок на файл», который описан в первом P0.

## Порядок работ

Слоями, снизу вверх; каждый слой самостоятельно ценен и обратимо совместим:

1. `brain_core` (atomic + locks + grammar) → закрывает все три P0.
2. Перевод `brain-task`, MCP и cycles на ядро → снимает копипаст и расхождение фасадов.
3. Пакетирование и удаление `sys.path`-bootstrap → убирает version skew.
4. Frontmatter ролей и машинная escalation matrix → делает маршрутизацию проверяемой.
5. Единый источник маршрутизации «роль → модель» (`.cli-mapping.sh` становится проекцией
   матрицы, матрица переезжает из `wiki/` в конфиг) → снимает расхождение, из-за которого
   роль уходит на исчерпанную квоту.
6. Разделение dashboard render/data.

Пункт 5 не зависит от 1–3 (другие файлы) и может идти параллельно ядру.

## Риски

- **Регрессия очереди.** Задачи — единственное невосстановимое состояние, и переписывается
  именно писатель. Митигация: `tests/cases/07-task-launch.sh` расширить конкурентным
  сценарием ДО рефакторинга (red), плюс property-тест round-trip `parse(write(x)) == x`.
- **Разрыв установленной копии.** У пользователя уже лежат `~/.local/bin/brain-*` и
  `~/.local/share/brain/lib`. Переход на пакет требует шага миграции, иначе старые
  бинарники будут работать поверх нового lib. Митигация: `setup-brain-v2.sh` удаляет
  старые копии перед `pip install`, `brain-status` печатает версию ядра.
- **Тесты на shell завязаны на текущий CLI-контракт.** 18k LOC кейсов проверяют вывод
  команд. Фасады обязаны сохранить точный stdout/exit-code; изменения формата — отдельными
  тикетами.
- **Двойная работа с параллельными агентами.** Рефакторинг ядра нельзя вести
  инкрементально несколькими агентами: тикеты 1–3 должны идти последовательно
  (`depends_on`), иначе конфликт правок в тех же файлах.
- **Объём.** ~24k LOC затронуто частично. Риск «большого взрыва» реален; поэтому
  тикеты нарезаны так, чтобы каждый оставлял систему рабочей.

## Альтернативы

**A. Ничего не менять, закрыть только P0 точечно.** Добавить `flock` в четыре heredoc'а
`brain-task` и починить stale-reclaim. Дёшево (одна сессия), убирает потерю данных.
Отвергнуто как целевое: не решает расхождение грамматик и оставляет четыре фасада —
следующее расхождение придёт с очередной фичей. Принято как **первый шаг** (тикеты 1–2)
внутри общего плана.

**B. Переписать очередь на SQLite, markdown генерировать как проекцию.** Снимает
конкурентность полностью и бесплатно. Отвергнуто: `tasks/active.md` — человекочитаемый
файл под git, это осознанная конституционная черта Brain (человек правит руками, история
в коммитах). SQLite ломает и ревью диффом, и правило приоритета ручной курации.

**C. Полный переход на Python-пакет с `console_scripts`, bash удалить целиком.**
Архитектурно чище всего. Отвергнуто в текущем цикле: `brain-orchestrator console`
и `launch-dashboard.sh` управляют tmux/процессами, где bash уместен, а стоимость
переписывания 15 bash-файлов не окупается сейчас. Оставлено как направление — правило 3
запрещает *новый* bash-код с логикой.

**D. Оставить дублирование, вынести только общий `brain_core.util`.** Полумера:
`brain_path`/`utc_now` схлопнутся, но писатели `active.md` останутся разными. Отвергнуто —
не адресует ни один P0.

## Тикеты

Декомпозиция — 15 тикетов в `tasks/active.md`, префикс `t-2026-08-10-core-*`
(3 × P0, 5 × P1, 7 × P2), у каждого указаны `role:`, `acceptance:` и, где есть, `depends_on:`.
Порядок обязателен для `atomic-taskfile` → `lock-race` → `task-grammar`: они правят одни
и те же файлы. `routing-single-source` идёт параллельно ядру.

Связанные страницы: [[decisions-log]], [[architecture-overview]], [[about-brain]],
[[workflow-solo-council]], [[decision-llm-stack]].
