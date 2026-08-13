---
title: Phase 13 PRD — Orchestrator Handoff, Provider Health, Visual Workflow
type: decision
created: 2026-05-07
updated: 2026-05-07
curation: agent
protected: false
source_policy: advisory
tags: [prd, phase-13, orchestrator, providers, ux]
sources: []
related: [decision-llm-stack, cli-agents, workflow-solo-council, council-guardrails]
visibility: public
---

# Phase 13 — Orchestrator Handoff, Provider Health & Visual Workflow

## Context

Phase 12 закрыл UI/UX skill pack (council-driven, contract finalised). Phase 13 — оперативный консолидационный цикл: устранить трения, всплывшие в Phase 11–12, и подготовить базу для масштабирования multi-agent пайплайна.

Три наблюдаемых проблемы:

1. **Handoff hiccups.** За последние сутки orchestrator сделал ≥4 `limit-near` хэндоффа на одной задаче (`t-2026-05-07-phase-13-planning-write-prd-an`). Файл хэндоффа перезаписывается без истории — теряется trail.
2. **Provider health «unavailable».** `brain-status` рапортует `roles=6 configured=6 unavailable=6`. Health-кэш либо никогда не пишется, либо TTL=∞ и протух. Это превращает provider-matrix в украшение.
3. **Visual workflow.** Dashboard показывает counters/SSE, но нет картины «кто чем занят сейчас», истории хэндоффов и провайдер-fallback цепочек. Невозможно за 5 секунд увидеть, где застряли.

## Goals

- **G1.** Orchestrator handoff = append-only journal + structured payload, читаемый CLI и dashboard'ом.
- **G2.** Provider health = реальные данные с TTL и явным fallback decision'ом, без сжигания квоты на каждом `brain-status`.
- **G3.** Visual workflow = single-pane «activity» view: задача → роль → провайдер → последний хэндофф → next-step.

## Non-goals

- Не переписываем CLI mapping или MCP tooling.
- Не вводим новых ролей/team'ов.
- Не трогаем council guardrails (Phase 11 doctrine стоит).

## Scope (10 tickets)

### Orchestrator handoff (G1) — 3 tickets
- T1 `phase13-handoff-journal` — append-only `handoff/journal.ndjson`, ротация по дням; `ORCHESTRATOR_HANDOFF.md` остаётся как «latest» view, генерируется из journal.
- T2 `phase13-handoff-cli` — `brain-handoff list|show|tail` поверх journal; фильтры по task/agent/reason.
- T3 `phase13-handoff-reasons` — нормализованный enum `reason` (`limit-near`, `limit-exhausted`, `rate-limit`, `context-bleed`, `manual`, `done`); валидируется в schema.

### Provider health (G2) — 3 tickets
- T4 `phase13-health-probe` — `brain-providers probe [--role R]`: явный, опт-ин, кэширует в `.provider-health.json` с `checked_at`/`ttl_sec`; default TTL=15m.
- T5 `phase13-health-status` — `brain-status` и dashboard читают кэш и показывают `healthy|stale|unknown|unavailable` вместо сырого `unavailable`. Никаких live probes из status.
- T6 `phase13-health-fallback-trace` — при роутинге логировать в journal выбранный rank и причину пропуска rank=1 (e.g. `quota_exceeded@2026-05-07T09:02Z`).

### Visual workflow (G3) — 3 tickets
- T7 `phase13-dashboard-activity` — в dashboard блок «Activity»: in-progress задачи × текущий agent × роль × провайдер × секунд с last refresh lock.
- T8 `phase13-dashboard-handoffs` — блок «Recent handoffs» (последние 10 из journal), цвет по `reason`.
- T9 `phase13-dashboard-provider-card` — на каждую роль карточка с rank-цепочкой и health-бейджем.

### Closeout — 1 ticket
- T10 `phase13-closeout` — release-notes, smoke (handoff journal + health probe + dashboard render), тег `v7`.

## Acceptance (phase-level)

- `brain-handoff tail -n 5` показывает последние записи на любой машине; журнал переживает 10 хэндоффов без потерь.
- `brain-status` после `brain-providers probe` показывает ≥1 провайдера в состоянии `healthy` per role; не делает сетевых вызовов сам.
- Dashboard render (`brain-dashboard export`) включает Activity/Handoffs/Provider-cards и проходит smoke.
- Все 10 тикетов закрыты, `done.md` обновлён, тег `v7` поставлен.

## Risks

- **R1.** Probe quota burn — митигируется opt-in + TTL + кэшем; никакого probe из status/dashboard.
- **R2.** Journal grows unbounded — daily rotation `journal-YYYY-MM-DD.ndjson`, retention 30 дней.
- **R3.** Schema drift в reason enum — вынести в `runtime/schemas/handoff.json`, валидировать на write.

## Sequencing

1. T3 (schema) → T1 (journal) → T2 (CLI) — handoff blok последовательно, остальное может ехать параллельно.
2. T4 → T5/T6 параллельно после T4.
3. T7/T8/T9 параллельно после T1+T4.
4. T10 — финальный.

## Sketch: handoff record

```json
{
  "ts": "2026-05-07T09:34:01Z",
  "task": "t-2026-05-07-phase-13-planning-write-prd-an",
  "from_agent": "codex-gpt55-architect-phase13-pty",
  "to_role": "architect",
  "reason": "limit-near",
  "provider_from": {"provider": "codex", "model": "gpt-5.5", "rank": 1},
  "provider_to": {"provider": "claude", "model": "opus-4.7", "rank": 2},
  "note": "context_pct=92"
}
```

## References

- [[decision-llm-stack]] — текущий стек, источник истины для rank.
- [[cli-agents]] — CLI surface, в который встраиваем `brain-handoff` / `brain-providers`.
- [[workflow-solo-council]] — режимы исполнения, не меняются.
