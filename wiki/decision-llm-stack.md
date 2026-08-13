---
title: Decision — LLM Stack for Brain Roles
type: decision
created: 2026-05-03
updated: 2026-05-06
curation: agent
protected: false
source_policy: advisory
tags: [decision, llm, models, roles]
sources: []
related: [roles-overview, about-brain, decision-role-model-routing]
visibility: public
---

# Decision: LLM Stack for Brain Roles

**Статус:** принято  
**Дата обновления:** 2026-05-06  
**Machine mapping:** `config/routing.json`
Маршруты ниже — проекция `config/routing.json`. Правится конфигурация,
блок обновляется командой `brain-provider render-doc`, расхождение ловит
`brain-validate`. Собственных списков страница больше не держит: прежние
разошлись с машинным источником по пяти ролям из шести.

## Маршруты по ролям

<!-- routing:begin -->

_Блок сгенерирован из `config/routing.json` — правь конфигурацию, не текст._

**Провайдеры вне игры:** `gemini` — отключён решением оператора 2026-08-10

| Профиль | Роли | Порядок кандидатов |
|---|---|---|
| `analysis-with-code` | `accountant`, `cfo`, `growth-analyst` | claude/opus → codex/gpt-5.5 (high) → opencode |
| `architecture` | `architect` | claude/opus → codex/gpt-5.5 (xhigh) → gemini/gemini-3.1-pro |
| `deep-research` | `researcher` | claude/opus → opencode → codex/gpt-5.5 (medium) |
| `heavy-legal` | `compliance`, `lawyer`, `tax-advisor` | claude/opus → claude/sonnet |
| `implementation` | `developer` | opencode → claude/sonnet → codex/gpt-5.3 (medium) |
| `independent-review` ⇄ | `impeccable-reviewer`, `reviewer`, `security`, `taste-reviewer` | opencode/deepseek-v4-pro → claude/opus → codex/gpt-5.5 (high) |
| `linear-legal` | `paralegal` | claude/sonnet → claude/opus |
| `ops` | `sre` | claude/sonnet → opencode |
| `strategy` | `copywriter`, `delivery`, `designer`, `maintainer`, `negotiator`, `pm`, `product`, `renovation-planner`, `strategist` | claude/opus → claude/sonnet |
| `synthesis` ⇄ | `arbiter` | claude/opus → opencode → codex/gpt-5.5 (xhigh) |
| `verification` | `qa` | claude/sonnet → opencode |
| `wiki-maintenance` | `linter`, `skill-curator`, `tech-writer`, `triage` | opencode → claude/sonnet → codex/gpt-5.5 (medium) |

⇄ — роль не идёт к провайдеру автора работы (правило диверсификации).

<!-- routing:end -->

## Правило диверсификации

- Для `reviewer` и `arbiter` по возможности использовать провайдер, отличный от текущего `developer` в конкретной задаче.
- В council-сценариях фиксировать выбранную модель в логе/комментарии к задаче.

## Операционное применение

- `brain-launch` спрашивает команду у `brain-provider cli`; политика — в `config/routing.json`.
- Пункты 2 и 3 в каждом списке — fallback при лимитах/недоступности primary.
- Машиночитаемый контракт хранится в `config/routing.json`; dashboard/API
  читают его без live provider probes по умолчанию.
- Приоритет: `--cli`/`BRAIN_CLI_OVERRIDE` → клиент, закреплённый скиллом за задачей
  → `config/routing.json` → `defaults.cli`.
- Ручные правки пользователя выше автогенерированных рекомендаций и источников.


## Политика для юридического и исследовательского блоков

### Юридический блок
- **Объёмные/сложные задачи** (структурирование позиции, многокомпонентные кейсы, большой корпус документов):
  1. Opus 4.7
  2. Gemini 3.1 Pro
  3. Sonnet 4.6

- **Менее сложные юридические задачи** (составление договоров, линейных документов, шаблонов):
  1. Sonnet 4.6
  2. Opus 4.7
  3. Gemini 3.1 Pro

### Исследовательский блок
- **Объёмные исследовательские задачи** (deep-dive, длинные сравнения, synthesis по нескольким источникам):
  1. Opus 4.7
  2. Gemini 3.1 Pro
  3. codex 5.3 medium

## Routing matrix (утверждено 2026-05-04)

### Критерии повышения модели

| Критерий | Когда повышаем модель |
|---|---|
| Объём контекста | много документов, длинные договоры, переписка, источники, несколько версий |
| Цена ошибки | налоговые/юридические последствия, внешняя отправка, позиция для суда/переговоров |
| Неопределённость | противоречивые источники, нет явного шаблона, надо строить позицию |
| Синтез | нужно не просто извлечь факты, а сделать вывод/стратегию |
| Формальность результата | договор, претензия, заключение, decision-doc |
| Срочность/стоимость | если задача линейная, не тратить Opus |

### Legal routing

`heavy legal / strategic legal`  
1. Opus 4.7 — сложные правовые позиции, структура сделки, спорные вопросы, большой корпус документов  
2. Gemini 3.1 Pro — независимое мнение, длинный контекст, сравнение источников  
3. Sonnet 4.6 — fallback для сложных, но не максимальных задач

`linear legal / drafting`  
1. Sonnet 4.6 — договоры, письма, акты, типовые положения, правка формулировок  
2. Gemini 3 Flash — быстрый черновик и варианты формулировок  
3. Codex 5.3 medium — структурирование Markdown, шаблоны, массовые правки файлов

`tax / compliance edge cases`  
1. Opus 4.7 — спорные или дорогие налоговые решения  
2. Gemini 3.1 Pro — независимая проверка и ресерч норм  
3. Sonnet 4.6 — оформление вывода и документов

### Research routing

`deep research / synthesis`  
1. Opus 4.7 — финальный синтез, выводы, стратегия, оценка противоречий  
2. Gemini 3.1 Pro — сбор и сравнение большого массива источников  
3. Codex 5.3 medium — упаковка результата в wiki, таблицы, индексы

`source harvesting / первичный сбор`  
1. Gemini 3.1 Pro — основной кандидат для поиска и длинного контекста  
2. Gemini 3 Flash — быстрый первичный сбор  
3. Sonnet 4.6 — аккуратное резюме и нормализация выводов

`research review / проверка качества`  
1. Opus 4.7 — критика сложного synthesis  
2. Gemini 3.1 Pro — независимая проверка источников  
3. Codex 5.5 high — проверка структуры, ссылок и полноты acceptance

### Практическое правило

- Opus 4.7: думать, синтезировать, решать, когда дорого ошибиться.
- Sonnet 4.6: писать юридические документы и рабочие тексты.
- Gemini 3.1 Pro: искать, сравнивать, давать независимый взгляд.
- Gemini 3 Flash: быстро черновить и выполнять лёгкие проходы.
- Codex 5.3/5.5: структурировать, править файлы, проверять контракты, автоматизировать.
