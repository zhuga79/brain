---
parent: <task-id>
created: <ts>
status: draft
---

# PRD: <Title>

## Goal
<Что должно быть сделано в одном абзаце. Какой результат>

## Why
<Зачем. Какая проблема решается. Какая гипотеза.>

## Scope
### In scope
-
### Out of scope (non-goals)
-

## Constraints
<Технические, временные, бюджетные ограничения>

## Decomposition rationale
<Почему именно такая декомпозиция. Какие альтернативы рассмотрены.>

## Acceptance for parent task
<Когда родительская PRD-задача считается выполненной — обычно после того,
как все сабтаски выполнены и интеграционные acceptance работают>

## Subtasks

> Формат: каждый сабтаск — markdown-чекбокс с метаданными.
> ID автогенерится на основе parent: <parent>-s1, <parent>-s2, ... либо
> можно задать явно после "—".
> depends_on: ссылается на ранее перечисленные id или на другие задачи.

- [ ] [P1] s1 — Название первого сабтаска
      role: developer
      depends_on: []
      acceptance: что считается готовым
      ref: [[wiki/...]]

- [ ] [P1] s2 — Название второго
      role: developer
      depends_on: [s1]
      acceptance: ...

- [ ] [P2] s3 — Документация
      role: researcher
      depends_on: [s2]
      acceptance: ...
