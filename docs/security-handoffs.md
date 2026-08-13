---
title: Security and Handoffs
type: concept
created: 2026-05-16
updated: 2026-05-16
curation: agent
protected: false
source_policy: advisory
tags: [security, handoff]
sources: []
related: [architecture-overview]
visibility: public
---

# Security and Handoffs

Security perimeters and payload delegation mechanisms in Brain.

## Security
- **Local Secret Vault**: Stores API keys and sensitive tokens outside of tracked artifacts.
- **GDrive Backup Script**: Resolves paths securely for remote backup.
- **Webhook URL Validation**: Scheme and address validation to prevent SSRF.

## Handoffs
- **Orchestrator Fallbacks**: Graceful fallback when execution limits are hit.
- **Handoff Parsing**: Parses auto-handoff payloads from agent output.
- **Webhook Formatters**: Translates events to Slack and Telegram schemas.

## Аудит shell-инъекций в bash-слое (2026-08-11)

Разбор мест, где внешние значения попадают в командную строку, собираемую
конкатенацией и исполняемую через `bash -lc` или `eval`.

| Место | Значения | Достижимость | Состояние |
|-------|----------|--------------|-----------|
| `brain-common:build_role_command` | роль, id задачи, id агента | Высокая: id задачи приходит аргументом `brain-launch <task>`, id агента — из `--agent`. Значение попадает в строку, которую исполняет `bash -lc`. | Закрыто: `validate_id` для всех трёх плюс `shell_quote` при подстановке |
| `brain-council:start` (арбитр) | id задачи, id агента | Высокая: строка идёт в `eval`. | Закрыто: `validate_id` на входе, `shell_quote` перед `eval` |
| `brain-common:cli_for_role` | роль, id задачи в инлайн `python3 -c` | Была высокой: значения подставлялись в текст питон-скрипта. | Устранено в `t-2026-08-10-routing-resolver`: инлайн-скрипт заменён вызовом `brain-provider cli` с аргументами |
| `brain-launch` | id задачи | Высокая: позиционный аргумент. | Закрыто: `validate_id` при разборе аргументов |
| `brain-task` | id задачи | Средняя: проверка была, но своя и строже общей (без точки). | Закрыто: своя копия заменена вызовом общей `validate_id` |
| `brain-orchestrator:mapped_cli_for_role` | роль | Низкая: роль проверялась регулярным выражением до shell-out. | Устранено: shell-out удалён, вызывается резолвер напрямую |

Принцип: идентификатор с метасимволом **отвергается**, а не экранируется.
Легальный идентификатор их не содержит, а проверка и экранирование со временем
разъезжаются — цена расхождения здесь равна исполнению чужого кода в окне
агента. Экранирование при подстановке оставлено вторым рубежом.

Проверка: `tests/cases/86-shell-injection.sh` — метасимволы в роли, задаче и
агенте не приводят к исполнению (маркерный файл не создаётся).
