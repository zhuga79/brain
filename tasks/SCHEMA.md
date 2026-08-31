# Формат задач

Эта очередь — очередь разработки самого Brain. Работа по делу клиента живёт в
папке дела: рядом с материалами, в её `TASKS.md` и `LOG.md` (папка с `BRAIN.md`,
см. `brain-workspace`). Поэтому `client:` здесь — ошибка, а не пометка:
`brain-validate` на ней краснеет. Поля `client:`/`project:` описаны ниже, потому
что тот же формат задач используется в очередях дел.

```
- [ ] [P1] t-2026-05-01-example — Короткое название
      role: developer    mode: solo
      depends_on: [t-prev-1, t-prev-2]
      due: 2026-05-15    tags: #area
      Контекст в одно-два предложения.
      acceptance: что должно работать в конце.
      ref: [[wiki/page]] | raw/file.md
```

## Поля
- `[ ]` `[~]` `[x]` `[!]` — состояние
- `[P0|P1|P2]` — приоритет
- `t-YYYY-MM-DD-<slug>` — id
- `role:` — роль из `roles/*.md`; базовые: `architect`/`developer`/`reviewer`/`security`/`researcher`/`linter`/`arbiter`
- `mode:` — `solo` (default) / `council` / `prd`
- `council:` — для mode=council: список ролей `[architect, reviewer]`,
  команд `[team:legal]` либо смесь
- `depends_on:` — id задач, которые должны быть `[x]`, прежде чем эта станет available.
  **Синтаксис:** `depends_on: [task-id-1, task-id-2, ...]` — bracketed list, comma-separated.
  Пустые компоненты запрещены: `[,]`, `[dep,]`, `[,dep]`, `[dep,,other]` → ошибка парсинга.
  Дубликаты внутри списка запрещены: `[task-x, task-x]` → ошибка парсинга.
  Поле `depends_on` может встречаться **только один раз** на задачу; повторное поле → ошибка парсинга.
  Поле распознаётся в любой позиции среди полей строки продолжения (используется общий парсер `grammar.parse_fields`).
- `due:` — опционально
- `tags:` — опционально
- `acceptance:` — обязательно
- `ref:` — ссылки на контекст
- `client:` — только в очереди дела. Заказчик, от которого идут деньги и часы
  (`ООО Ромашка`); единица биллинга — отчёты и учёт времени агрегируются по нему.
- `project:` — только в очереди дела. Направление внутри заказчика
  (`Аренда-складов`), единица организации работы. У простого дела совпадает
  с `client:`; отдельным его пишут, когда у одного заказчика несколько дел.
- `surface:` — `headless` (default) / `interactive`. `interactive` = исход зависит
  от диалога с человеком → задача запускается в видимом окне (tmux/терминал/чат),
  оркестратор НЕ берёт её в headless auto-next. См. [[decision-interactive-surface]].
- `gate:` — опц., тип человеческого шлюза для `surface: interactive`:
  `approval|taste|legal|intake|arbiter|data|risk|secret|curation`.

## Fail-closed поведение зависимостей

Парсер (`parse_local_tasks` / `parse_local_tasks_from_text`) **строго отклоняет** невалидные задачи **до** построения графа/селекции/мутации. Проверяемые случаи (перечисление не задаёт порядок выполнения):

- **Дубликаты task_id** — если в файле встречаются два блока с одинаковым id, парсинг прерывается с `ValueError: Duplicate task ID: <id>`. Это гарантирует детерминизм: карта состояний не зависит от порядка блоков.
- **Пустые компоненты `depends_on`** — `[,]`, `[task-a,]`, `[,task-a]`, `[task-a,,task-b]` → `ValueError: Malformed depends_on list (empty component): <value>`.
- **Дубликаты внутри `depends_on`** — `[task-x, task-x]` → `ValueError: Task <id> has duplicate dependency: task-x`.
- **Дубликаты поля `depends_on`** — два `depends_on:` в одном блоке → `ValueError: Task <id> has duplicate depends_on field`.
- **Самозависимость** — `depends_on: [task-a]` в задаче `task-a` → `ValueError: Task task-a has self-dependency in depends_on`.
- **Отсутствующие зависимости** — `depends_on: [missing-id]` → `ValueError: Task <id> has missing dependency: missing-id`.
- **Циклы** — `A → B → A` → `ValueError: Dependency cycle detected involving: <node>`.

**Поведение операций `next_local_task` / `take_local_task` / `complete_local_task`:**

- `next_local_task`: пропускает задачи с невыполненными deps (возвращает `None`, если доступных нет). Не мутирует файлы.
- `take_local_task`: если у задачи есть невыполненные deps — **отклоняет с `ValueError` до любой мутации** `TASKS.md` или `LOG.md`. Состояние задачи остаётся `[ ]`, лог не пишется.
- `complete_local_task`: если у задачи есть невыполненные deps — **отклоняет с `ValueError` до любой мутации** `TASKS.md` или `LOG.md`. Состояние задачи остаётся `[~]`, лог не пишется.

## Машинное состояние во время работы
Когда задача в работе, к ней дописывается:
```
      started: 2026-05-01T10:30:00+00:00
      by: claude-opus-7f3a
```

## Council
Для `mode: council` каждый член совета пишет в `council/<id>/<role>.md`.
Запуск: `brain-council start <id>`. Синтез: `brain-council synthesize <id>`.

## mode: prd

Крупная работа: `architect` заполняет `prd/<id>.md`, `brain-prd commit <id>`
раскладывает сабтаски в очередь с проставленными `depends_on`.
