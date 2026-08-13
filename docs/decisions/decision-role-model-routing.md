---
title: Decision — Маршрутизация «роль → модель»: один машинный источник
type: decision
created: 2026-08-10
updated: 2026-08-10
curation: agent
protected: false
source_policy: advisory
tags: [decision, routing, providers, roles, runtime]
sources: []
related: [decision-runtime-core-boundaries, decision-llm-stack, roles-overview, decisions-log, architecture-overview]
visibility: public
---

# Decision: маршрутизация «роль → модель» — один машинный источник

**Статус:** предложено
**Задача:** `t-2026-08-10-core-routing-single-source`
**Роль:** architect (`operator-architect-1174360`)
**Родитель:** [[decision-runtime-core-boundaries]], пункт 5 порядка работ

## Контекст: источников не три, а четыре

| # | Источник | Формат | Кто читает |
|---|----------|--------|------------|
| 1 | `.cli-mapping.sh` | bash-строки `cli_for_<role>` | `brain-common:cli_for_role` → `brain-launch` (3 точки), `brain-council` (3), `brain-prd`; `brain-orchestrator:mapped_cli_for_role` (через `bash -lc source`) |
| 2 | `wiki/provider-matrix.json` | JSON, ранжированные кандидаты | `brain_provider.load_provider_matrix` → `brain-provider status/refresh/probe`, `brain-orchestrator:490` (резолв кандидата для fallback-handoff), `brain-prd:56`, `brain_dashboard/data.py:515` |
| 3 | `brain_provider.DEFAULT_MATRIX` | Python-литерал | тот же `load_provider_matrix`, когда файла нет |
| 4 | [[decision-llm-stack]] | проза | человек |

Источник 3 в исходной формулировке задачи не назван, но это полная копия источника 2
внутри кода (`runtime/lib/brain_provider.py:32-86`), обновляемая отдельно. Он уже разошёлся
с файлом: в `DEFAULT_MATRIX` шесть ролей, в JSON — девять.

### Замер расхождения на 2026-08-10

| Роль | `.cli-mapping.sh` | `provider-matrix.json` rank 1 | [[decision-llm-stack]] |
|------|-------------------|-------------------------------|------------------------|
| architect | `claude --model opus` | codex gpt-5.5 xhigh | codex 5.5 xhigh |
| developer | `opencode run` | gemini-3-flash | Gemini 3 Flash |
| reviewer | `opencode run -m opencode/deepseek-v4-pro` | gemini-3.1-pro | Gemini 3.1 Pro |
| researcher | `claude` | gemini-3.1-pro | Gemini 3.1 Pro |
| linter | `opencode run` | codex gpt-5.5 medium | codex 5.5 medium |
| arbiter | `claude` | claude opus-4.7 | Opus 4.7 |

Совпадает одна роль из шести. Провайдер `opencode`, на котором фактически работают три
роли, в матрице отсутствует как класс — значит, его здоровье не отслеживается, а
`brain-provider status` рапортует о провайдерах, которых никто не запускает. Обратно:
`gemini` отключён оператором и `codex` исчерпал квоту до 2026-09-07 (записано комментарием
в bash), но матрица продолжает называть их первым выбором для пяти ролей.

Цена расхождения зафиксирована: задача `t-2026-08-10-brain-runtime-48-12k-loc-49-c`
ушла на `codex` по матрице, получила `fallback_reason: quota_exceeded` и была передана
по handoff другому агенту.

### Покрытие ролей

`roles/` — 28 файлов. Записи о маршруте есть у 14 ролей: 9 в матрице
(`architect, developer, reviewer, researcher, linter, arbiter, qa, sre, tech-writer`),
11 в `.cli-mapping.sh` (те же шесть плюс `lawyer, tax-advisor, compliance, paralegal,
growth-analyst`). Остальные 14 — включая `security`, `cfo`, `product`, `designer`,
`negotiator` — молча уходят в `CLI_DEFAULT="claude"` без модели, то есть на дефолт CLI.
Правило MEMORY.md «для `security` — мощная модель другого провайдера» не исполняется нигде.

Отдельно: реестр ролей в `MEMORY.md` перечисляет 24 роли, а `roles/` содержит 28
(нет `qa`, `sre`, `tech-writer`, `skill-curator`). Это тот же шов, что и в матрице,
и он закрывается тикетом `t-2026-08-10-core-escalation-machine`.

### Почему сломалось именно так

Разошлись не «две копии одного списка», а **два разных вида знания, слитые в один файл**:

- *политика* — какую модель мы хотим для роли (решение архитектора, живёт в git, ревьюится диффом);
- *доступность* — что работает на этой машине прямо сейчас (квота, отключённый CLI, rate limit).

Место для доступности в системе есть — `.provider-health.json` со статусами
`quota-exhausted`/`rate-limited` и TTL (`brain-provider mark --ttl-seconds`), и
`collect_provider_status` уже умеет фильтровать по нему и выдавать `preferred`/`fallback`.
Но оператору некуда было записать «codex до 2026-09-07 не трогать» в момент инцидента,
кроме как переписать политику в `.cli-mapping.sh`. Факт доступности был записан в файл
политики — и политика разъехалась.

Второй структурный дефект: `.cli-mapping.sh` физически не способен выразить ранг и
здоровье. Он отдаёт ровно одну строку. Поэтому `brain-launch` и `brain-council` **не
имеют fallback вообще** — при недоступном CLI они просто падают; автоматический fallback
есть только у `brain-orchestrator`, который читает другой источник.

Третий: `.cli-mapping.sh` лежит в `RUNTIME_PATHS` федерации (не синхронизируется как
машинно-локальный), но при этом в `ALLOW_FILES` `brain-publish` (публикуется). Один файл
классифицирован как локальный и как общий одновременно.

## Решение

Разделить четыре слоя знания, дав каждому ровно одного владельца.

| Слой | Владелец | В git | Кто пишет |
|------|----------|-------|-----------|
| Политика: ранжированные кандидаты по ролям | `config/routing.json` | да | человек/architect, диффом |
| Доступность: квоты, rate limit, отключённые CLI | `.provider-health.json` | нет (машинно-локально) | `brain-provider mark/probe/refresh` |
| Резолв: политика ∩ доступность → команда | `brain_provider.resolve_for_role()` | код | — |
| Обоснование и критерии выбора | [[decision-llm-stack]] | да | человек |

Правила:

1. **`config/routing.json` — единственный машинный источник политики.**
   Вне `wiki/`: слой знаний курируется человеком по контракту `curation`/`protected`
   и валидируется как markdown-страницы; конфиг исполнения нуждается в схеме, версии и
   машинной записи. Вне `.brain/` — он в `.gitignore`, а решение о маршрутизации обязано
   быть в истории коммитов.
2. **`wiki/provider-matrix.json` удаляется.** `brain_provider.matrix_path()` указывает
   на новый путь; `brain-orchestrator`, `brain-prd`, `brain_dashboard/data.py` идут через
   ту же функцию и правки не требуют.
3. **`brain_provider.DEFAULT_MATRIX` перестаёт быть копией политики.** Остаётся
   bootstrap-минимум (`CLI_DEFAULT`, пустой `roles`) и WARN «config/routing.json не найден».
   Дефолт, дублирующий политику, — это четвёртый источник, а не отказоустойчивость.
4. **`.cli-mapping.sh` удаляется.** `brain-common:cli_for_role` вызывает
   `brain-provider cli --role <role> [--task <id>]`; `brain-orchestrator:mapped_cli_for_role`
   вызывает `brain_provider.resolve_for_role()` напрямую (модуль уже импортирован) и
   больше не шеллаутит в bash.
5. **Порядок приоритета** (единственная цепочка, реализованная в одном месте —
   `resolve_for_role`):
   `--cli`/`BRAIN_CLI_OVERRIDE` → пин из скилла (`brain_skill_parser.get_pinned_client_for_task_role`)
   → первый здоровый кандидат роли из `config/routing.json` → `defaults.cli`.
   Существующий блок `manual_override_priority` в матрице переписывается под неё.
6. **Каждая роль из `roles/` имеет запись.** Чтобы 28 ролей не превратились в 28 руками
   поддерживаемых списков, вводится уровень **профилей**: роль → профиль, профиль →
   ранжированный список кандидатов. Роль может переопределить список целиком.
   Существующий блок `routes` (`heavy_legal`, `linear_legal`, `deep_research`, …) — это
   и есть профили; он поглощается новой секцией `profiles`, отдельной сущности не остаётся.
7. **Присвоение профиля роли явное**, не выводится из имени и не наследуется по умолчанию:
   молчаливый дефолт — это ровно та ошибка, из-за которой 14 ролей сейчас уходят в
   `CLI_DEFAULT`. Роль без профиля — ошибка валидации, а не «возьмём общий».
8. **Проза не дублирует списки.** [[decision-llm-stack]] сохраняет критерии повышения
   модели, правило диверсификации и практические правила; таблицы приоритетов заменяются
   генерируемым блоком между маркерами `<!-- routing:begin -->` / `<!-- routing:end -->`,
   который рендерит `brain-provider render-doc`. Текст вне маркеров остаётся человеческим.
9. **`brain-validate` падает** (ERROR) при: роли из `roles/*.md` без разрешимой записи;
   нечитаемом или неизвестной версии `config/routing.json`; дублирующемся `rank` внутри
   роли; ссылке на профиль или провайдера, которых нет; присутствии удалённых
   `wiki/provider-matrix.json` или `.cli-mapping.sh`; расхождении генерируемого блока
   в [[decision-llm-stack]] с текущим конфигом. WARN — когда исполняемого файла кандидата
   нет на машине и нет записи о здоровье.

### Схема `config/routing.json` (v2)

```jsonc
{
  "schema": 2,
  "updated": "2026-08-10",
  "defaults": { "cli": "claude" },
  "providers": {
    "claude":   { "command": "claude",   "enabled": true },
    "opencode": { "command": "opencode run", "enabled": true },
    "codex":    { "command": "codex",    "enabled": true },
    "gemini":   { "command": "gemini",   "enabled": false,
                  "note": "отключён оператором 2026-08-10" }
  },
  "profiles": {
    "architecture": [
      { "rank": 1, "provider": "claude", "model": "opus", "use_for": "проектирование, ADR" },
      { "rank": 2, "provider": "codex",  "model": "gpt-5.5", "effort": "xhigh" },
      { "rank": 3, "provider": "gemini", "model": "gemini-3.1-pro" }
    ],
    "independent-review": [
      { "rank": 1, "provider": "opencode", "model": "deepseek-v4-pro" },
      { "rank": 2, "provider": "claude",   "model": "opus" }
    ]
  },
  "roles": {
    "architect": { "profile": "architecture" },
    "reviewer":  { "profile": "independent-review", "diversify_from_author": true },
    "developer": { "profile": "implementation" }
  }
}
```

`enabled: false` у провайдера — это политика (оператор выключил CLI), в отличие от
`quota-exhausted` в `.provider-health.json` — это факт, который истекает по TTL.
Разница существенна: политику видно в диффе и она переживает `brain-provider clear`.

### Начальное присвоение профилей (28/28)

| Профиль | Роли |
|---------|------|
| `architecture` | architect |
| `implementation` | developer |
| `independent-review` | reviewer, security, taste-reviewer, impeccable-reviewer |
| `synthesis` | arbiter |
| `deep-research` | researcher |
| `wiki-maintenance` | linter, tech-writer, skill-curator |
| `verification` | qa |
| `ops` | sre |
| `heavy-legal` | lawyer, compliance, tax-advisor |
| `linear-legal` | paralegal |
| `analysis-with-code` | growth-analyst, cfo, accountant |
| `strategy` | strategist, product, pm, designer, copywriter, negotiator, delivery, renovation-planner |

Профили `independent-review` и `synthesis` несут `diversify_from_author: true` —
машинная форма правила диверсификации из MEMORY.md. Резолвер принимает
`--not-provider <p>` и пропускает кандидатов этого провайдера; `brain-council` передаёт
провайдера автора мнения. Сегодня это правило исполняется руками и захардкожено
одной строкой `deepseek-v4-pro` для `reviewer`.

## Обоснование

**Почему удалить `.cli-mapping.sh`, а не генерировать его.** Генерация оставляет второй
артефакт, который выглядит редактируемым — а именно ручная правка этого файла и породила
инцидент. Заголовок `# GENERATED` расхождение не предотвращает, а лишь делает его молчаливым:
следующий `render` затрёт правку оператора, сделанную в 3 часа ночи по живой проблеме.
Кроме того, bash-строка структурно не вмещает ранг и здоровье, поэтому генерация
сохранила бы главный дефект — отсутствие fallback у `brain-launch`/`brain-council`.

**Цена вызова python из bash.** `cli_for_role` вызывается только на реальном запуске
агента (7 точек в трёх CLI), а не на каждой команде: `.cli-mapping.sh` сегодня сорсится
в `brain-common` при каждом запуске любого `brain-*`, а функция дёргается редко.
Резолвер читает два небольших JSON. При этом `cli_for_role` уже сегодня запускает
python-подпроцесс для skill-pin — то есть подпроцесс на этом пути не новый, а
единственный вместо двух.

**Почему профили, а не 28 списков.** 28 независимых списков разойдутся при первом же
изменении модельного парка (их уже нужно править в двух местах при каждом релизе модели).
Профиль — это то, что архитектор реально решает: «эта роль думает», «эта роль пишет
документы», «эта роль проверяет другого». Смена парка моделей — правка 12 профилей.

**Почему валидация сравнивает прозу с конфигом через генерируемый блок.** «Противоречие
матрицы и прозы» на естественном языке неразрешимо машиной. Единственная проверяемая
формулировка — «блок в прозе побайтово равен рендеру конфига». Границы маркеров
сохраняют человеческую часть страницы и не нарушают контракт курации
(`decision-llm-stack` имеет `curation: agent`, `protected: false`).

## Риски

- **Резолвер становится единой точкой отказа запуска.** Если `brain-provider` сломан,
  не стартует ни один агент. Митигация: `resolve_for_role` при любой ошибке возвращает
  `defaults.cli`, пишет WARN в stderr и никогда не возвращает ненулевой код в путь запуска;
  тест на «повреждённый config/routing.json → запуск идёт на дефолте».
- **Разрыв установленной копии.** У пользователя лежат `~/.local/bin/brain-*` и
  `~/.local/share/brain/lib`. Старый `brain-common` продолжит сорсить удалённый
  `.cli-mapping.sh` и молча уйдёт в `CLI_DEFAULT`. Митигация: удаление файла и правка
  `brain-common` — один коммит; `brain-status` печатает источник маршрутизации;
  ERROR валидации на присутствие старых файлов ловит недомигрировавшую копию.
- **Публикация и федерация.** `config/routing.json` — новый путь: его нужно внести в
  `ALLOW_FILES`/`ALLOW_DIRS` `brain-publish`, иначе публичный репозиторий останется без
  маршрутизации, и убрать `.cli-mapping.sh` из `RUNTIME_PATHS` федерации и из allowlist
  публикации. Пропуск этого шага обнаружится только на следующем `brain-publish`.
- **Профиль может тихо назначить юридической роли кодовую модель.** Митигация: присвоение
  явное (правило 7), таблица профилей ревьюится диффом, `brain-provider status --role`
  печатает профиль в выводе.
- **Тесты на shell завязаны на текущий вывод.** `tests/cases/07-task-launch.sh` и
  `26-federation.sh` знают про `.cli-mapping.sh`. Правятся вместе с удалением файла,
  отдельным тикетом их не растягивать.
- **Диверсификация требует знать провайдера автора.** В `brain-council` он известен,
  в `brain-launch` — нет. Поэтому `diversify_from_author` вынесен в отдельный P2-тикет
  и до него ведёт себя как no-op.

## Альтернативы

**A. Генерировать `.cli-mapping.sh` из конфига.** Дёшево, не трогает `brain-common`.
Отвергнуто как целевое по причинам выше. Допустимо как переходный шим на один релиз,
если миграция установленных копий окажется болезненной; тогда файл обязан быть в
`.gitignore` и помечен как артефакт.

**B. Оставить матрицу в `wiki/`.** Ноль правок в путях. Отвергнуто: `wiki/` — слой
знаний с человеческой курацией и markdown-валидацией; `brain-publish` трактует
`wiki/*.json` как курируемый контент; конфиг исполнения там неотличим от знания.
Это прямо противоречит правилу 5 из [[decision-runtime-core-boundaries]].

**C. Положить маршрутизацию в `.brain/`.** Отвергнуто: `.brain/` в `.gitignore`,
политика исчезнет из истории и из федерации.

**D. Маршрут в frontmatter `roles/*.md`.** Привлекательно — рядом с персоной, и пара
к тикету `t-2026-08-10-core-roles-frontmatter`. Отвергнуто: нет общего вида (какие
роли на каком провайдере — вопрос, на который придётся отвечать грепом по 28 файлам),
профили и порядок между ролями не выражаются, дашборду пришлось бы парсить 28 markdown.
Компромисс: имя профиля может позднее переехать во frontmatter роли, но списки кандидатов
остаются централизованными, и владелец должен быть один — `core-roles-frontmatter` не
имеет права дублировать `roles` из `config/routing.json`.

**E. Оставить два источника, но добавить тест на равенство.** Отвергнуто: тест на
равенство двух источников — это признание, что источника два; он ломается ровно тогда,
когда оператор правит один из них по живой проблеме, то есть в момент инцидента.

## Декомпозиция

1. `t-2026-08-10-routing-config-move` — P1, developer. Схема v2, перенос из `wiki/`,
   `matrix_path()`, сжатие `DEFAULT_MATRIX`, publish/federation allowlists.
2. `t-2026-08-10-routing-resolver` — P1, developer, зависит от 1. `resolve_for_role()`,
   `brain-provider cli`, `brain-common`, `brain-orchestrator`, удаление `.cli-mapping.sh`.
3. `t-2026-08-10-routing-role-coverage` — P1, architect, зависит от 1. Профили,
   28/28 ролей, перенос фактов доступности (gemini выключен, codex до 2026-09-07,
   opencode как провайдер) из комментариев в `.provider-health.json`.
4. `t-2026-08-10-routing-validate` — P1, developer, зависит от 1 и 3. `validate_routing()`.
5. `t-2026-08-10-routing-doc-projection` — P2, developer, зависит от 4. Генерируемый
   блок в [[decision-llm-stack]] и golden-сравнение.
6. `t-2026-08-10-routing-diversify` — P2, developer, зависит от 2. `--not-provider`
   и передача провайдера автора из `brain-council`.
