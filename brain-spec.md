# brain — спецификация

> Phase 7: spec split into stable contract and living guide.
> Old monolithic spec preserved at the same path as a redirect stub.

## Структура

- **[spec/contract.md](spec/contract.md)** — стабильный контракт (ABI):
  файловая структура, формат задач, lock-protocol, council-protocol,
  PRD-режим, wiki-контракт, indexing, vector layer, policy profiles,
  таблица версий.
- **[spec/guide.md](spec/guide.md)** — живая документация:
  архитектура, реестр ролей, CLI/MCP справочник, doctrine, runbook,
  установка, тестирование, известные ограничения, roadmap, learning loop,
  cheat sheet, глоссарий.

## Quick reference

| Тема | Файл |
|---|---|
| TL;DR — за 30 секунд | [guide.md#tldr](spec/guide.md) |
| Архитектура | [guide.md#архитектура](spec/guide.md) |
| Реестр ролей | [guide.md#реестр-ролей](spec/guide.md) |
| Реестр команд | [contract.md#реестр-команд](spec/contract.md) |
| Формат задач | [contract.md#формат-задач](spec/contract.md) |
| Lock protocol | [contract.md#lock-protocol](spec/contract.md) |
| Council protocol | [contract.md#council-protocol](spec/contract.md) |
| PRD-режим | [contract.md#prd-режим](spec/contract.md) |
| Wiki & curation | [contract.md#wiki](spec/contract.md) |
| Indexing | [contract.md#indexing](spec/contract.md) |
| Vector layer | [contract.md#векторный-поиск](spec/contract.md) |
| CLI-инструменты | [guide.md#cli-инструменты](spec/guide.md) |
| MCP-сервер | [guide.md#mcp-сервер](spec/guide.md) |
| Policy Profiles | [contract.md#policy-profiles-phase-6](spec/contract.md) |
| Production Hardening | [guide.md#production-hardening-phase-6](spec/guide.md) |
| Learning Loop | [guide.md#learning-loop-phase-5](spec/guide.md) |
| Установка | [guide.md#установка](spec/guide.md) |
| Тестирование | [guide.md#тестирование](spec/guide.md) |
| Cheat sheet | [guide.md#cheat-sheet](spec/guide.md) |
| Глоссарий | [guide.md#глоссарий](spec/guide.md) |
| Версионирование | [contract.md#версионирование](spec/contract.md) |

## Versioning

Изменение в `spec/contract.md` требует bump в таблице версий (см.
[contract.md#версионирование](spec/contract.md)). `spec/guide.md` —
живой документ без bump-требований.

## Лицензия и атрибуция

См. репозиторий — лицензия и атрибуция применяются к проекту в целом.
