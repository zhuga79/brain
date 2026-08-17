---
title: Decision — Runtime Core: границы модулей и владельцы записи
type: decision
created: 2026-08-10
updated: 2026-08-17
curation: agent
protected: false
source_policy: advisory
tags: [decision, architecture, runtime, tasks, concurrency, workspace]
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
`doctrine/`, `skills/`, `spec/`, `docs/`, `config/`, `MEMORY.md`)
принадлежат system checkout. Data root не должен нести их вторую живую копию.

`teams/` — исключение уровня контракта, а не баг. Canonical system team
catalog остаётся system-owned и не зеркалируется в data root как вторая
истина. Но data-local и case teams допустимы, и при наличии одноимённого
файла precedence у `$BRAIN/teams` перед `$BRAIN_SYSTEM_PATH/teams`.

`setup-brain-v2.sh`, `brain-validate` и pre-commit write-path guard теперь
рассматривают system shadow в data root как ошибку эксплуатации.

### 8. Release gates описываются полным набором проверок

Текущий gate для system repo: smoke suite + pytest в CI и в локальном
pre-commit, плюс `brain-validate` / `brain-lint` в эксплуатационном цикле.
Документация не должна больше обещать «зелёный status» по одному smoke-only
сигналу.

### 9. Folder-native рабочая папка — сознательно ограниченный контур

**Вопрос (`t-2026-08-17-folder-native-workspace-contour`):** folder-native
рабочая папка (маркер `BRAIN.md`, `brain-workspace discover|tasks|next|take|
complete`) — полноправный контур Brain или сознательно ограниченный?

**Ответ: сознательно ограниченный.** Не по недосмотру — по продолжению
решения из раздела 5 этого документа: workspace-очередь уже отделена от
корневой намеренно (свой writer, свой lock, свой recovery journal). Полный
контур означал бы вторую реализацию совета, диверсификации провайдеров,
графа зависимостей и локов поверх другой схемы файлов ради папок, для
которых эта тяжесть не нужна — folder-native workspace создан для скромной
локальной очереди рядом с документами дела, не для замены корневой очереди
разработки Brain.

Пять мест тикета и это решение:

1. **`brain-council`, `brain-task`, `brain-lock` не читают `TASKS.md`.**
   Это не пробел, а граница: `validate_queue_scope` уже запрещает
   `client:`-задачи в `tasks/active.md` — очередь дела и очередь разработки
   Brain разделены с обеих сторон, не только с этой. Многоролевой обзор
   задачи дела получают не через `brain-council`, а вручную: несколько
   агентских сессий с разными `--role` над одной локальной задачей, мнения —
   в `council/` папки дела (конвенция, которую уже описывает шаблон
   workspace). Формализация этого как облегчённой версии `brain-council`
   возможна, но это отдельная работа, не требование этого решения.
2. **Автоопределение корня по `wiki/`+`tasks/` не работает при заданном
   `BRAIN_PATH`.** Это не дефект: `brain-workspace` не читает `BRAIN_PATH` и
   не угадывает корень по cwd вообще — он резолвит папку через
   `find_nearest_workspace` от `--workspace` или явного пути. Обёртка,
   подставляющая `BRAIN_PATH`, была нужна только чтобы направить *корневые*
   инструменты (`brain-task` и т.п.) на папку дела — а это как раз тот
   сценарий, который решение не поддерживает: если задаче нужны корневые
   инструменты, это признак того, что она принадлежит корневой очереди, а не
   обходного пути через `BRAIN_PATH`.
3. **`EXCLUSIVE_SYSTEM_DIRS` запрещает `docs/`, `tests/`, `config/`,
   `roles/` в рабочей папке.** Причина ограничения (см. комментарий у
   `EXCLUSIVE_SYSTEM_DIRS`, `validators.py:45`) — граница system/data при
   разделённых корнях: эти имена резолвятся `brain_resolve_system` с
   фолбэком на системный корень и несут исполняемую/доверенную поверхность
   (роли, конфиг маршрутизации, скиллы). Снимать её для входа в дерево
   *любой* папки на диске с `BRAIN.md` было бы неверно — папка дела может
   быть где угодно, в том числе вне контроля оператора Brain, и получила бы
   возможность подсунуть свои `roles/*.md` с другими `writes:`. Вместо снятия
   ограничения решение сужает его область: `brain-validate` (см. п. 5)
   вообще не применяет схему системного корня к folder-native рабочей
   папке, поэтому `EXCLUSIVE_SYSTEM_DIRS` там больше не проверяется и не
   мешает — `docs/`, `tests/`, `config/` в папке дела для собственных нужд
   легальны, а граница остаётся там, где она защищает настоящую систему:
   в раздельных корнях `$BRAIN`/`$BRAIN_SYSTEM_PATH`.
4. **Локальная `config/routing.json` перекрывает системную целиком.**
   Правило слияния для неё в этом решении не нужно, потому что снята сама
   причина — см. отдельные роли дела (ниже): формального механизма
   "локальная роль только для этой папки" в ограниченном контуре нет, а
   значит нет и необходимости добавлять её в матрицу маршрутизации только
   для одной папки. Слияние `config/routing.json` для собственно приватного
   корня (`$BRAIN`) — независимый и более широкий вопрос, этим решением не
   охватывается.
5. **`brain-validate` в контексте рабочей папки выдаёт неустранимые
   ошибки.** Исправлено: `validate_all` (`brain_wiki/validators.py`)
   теперь определяет folder-native рабочую папку по маркеру `BRAIN.md`
   (`is_folder_native_workspace`) раньше, чем требует `raw/`, `wiki/`,
   `tasks/active.md` — и возвращает один `INFO`-issue вместо ошибок по схеме,
   которой у такой папки нет и не должно быть. Проверка такой папки —
   `brain-workspace`, не `brain-validate`.

**Локальные роли дела** (в тикете — пример из живого дела: набор персон,
специфичных для одного случая) — легального места как *enforced*-роли внутри
рабочей папки нет и не появляется. `BRAIN.md`-секция `## Role Policy`
(`core`/`available`/`gated`/`blocked`) — существующее легальное место для
**локальной политики**, но она сужает применимость уже существующих системных
ролей, а не определяет новые персоны с собственными `writes`/`doctrine`.
Персона, нужная только внутри одной папки, — это прозаическое указание в её
`BRAIN.md` (агент читает и следует, но `brain-council`/routing её не знают).
Персона, которая должна быть настоящей ролью (проверяемой, маршрутизируемой,
входящей в диверсификацию reviewer/arbiter), заводится один раз обычным
путём — файлом в системном `roles/`, доступным всем деревьям.

**Что отвергнуто и почему:**
- *Единая реализация очереди для root и workspace.* Отвергнуто: две очереди
  решают разные задачи (полная система ролей/диверсификации/PRD против
  скромного локального журнала) и уже сознательно разделены разделом 5.
  Слияние увеличило бы поверхность workspace-транзакции ради возможностей,
  которые ей не нужны, и создало бы риск для `taskfile`-инвариантов ради
  папок вне контроля оператора Brain.
- *Снятие `EXCLUSIVE_SYSTEM_DIRS` для приватного дерева.* Отвергнуто:
  ограничение — единственный барьер, отделяющий доверенную конфигурацию
  системы от произвольной папки на диске с `BRAIN.md`. Вместо снятия —
  сужена область его действия (см. п. 3 и п. 5 выше).
- *Формальные локальные роли (свой `roles/` в рабочей папке).* Отвергнуто по
  той же причине: `roles/*.md` несёт `writes`, потенциально расширяющий
  права агента, и не должен становиться папкой, которую можно уронить в
  произвольное дерево. Именованная альтернатива — прозаическая персона в
  `BRAIN.md` или один системный `roles/*.md` — см. выше.

Документация границы — `spec/guide.md`, раздел `brain-workspace` → «Scope
boundary: deliberately limited, not a second root queue», и текст
`--help` самого `brain-workspace`.

**Тест:** `tests/python/test_brain_validators.py::TestValidateAllFolderNativeWorkspace`
— папка с `BRAIN.md`, `TASKS.md`, `LOG.md` и без `raw/`/`wiki/`/
`tasks/active.md` проходит `validate_all` без ERROR/WARN, получает один
`INFO`-issue, и полноприлагаемая схема (`REQUIRED_DIRS`,
`EXCLUSIVE_SYSTEM_DIRS`) к ней не применяется даже при наличии в ней
`docs/`, `tests/`, `config/`, `roles/`.

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
