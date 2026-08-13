# Doctrine: Design Review Workflow

Tiered UI design-review для Brain. Источник: council
`t-2026-06-25-synthesize-design-review-workflow` (ACCEPTED 2026-06-29),
сводящий ревью `taste-skill` (вкус) и `impeccable` (структура/детекторы).

## Принцип
taste-skill и impeccable — **два слоя одного конвейера**, не конкуренты:
- **impeccable** — детерминированная структура/a11y (машинно проверяемо → дёшево, headless).
- **taste-skill** — субъективный вкус (не верифицируем → человек в видимом окне).

Конвейер: **deterministic-first → taste-second → human-owns-verdict**.
Дорогое человеческое внимание тратится только там, где незаменимо.

## Два уровня
- **L1 — Detector lint** (на каждый UI-diff): `brain-uiux-lint` гоняет
  detector-подмножество impeccable по `wiki/_views/brain-dashboard.html`.
  Advisory → обязательный после baseline/allowlist.
- **L2 — Design Review Council** (по триггеру).

## Триггеры L2
- Новый UI screen/flow/component на 2+ роли → `[product, designer, developer, reviewer]`.
- Внешние design-agent практики / спорный UI quality-gate → `council: [team:design-review]`.

## Конвейер L2 (порядок неслучаен)
1. **impeccable-reviewer** `surface: headless` — detector-gate: контраст
   (body ≥4.5:1 / large ≥3:1), Absolute-bans (side-stripe borders, gradient
   text, glassmorphism-default, hero-metric, identical card grids, eyebrow,
   numbered markers, text-overflow), z-index scale, line-length 65-75ch,
   prefers-reduced-motion.
2. **taste-reviewer** `surface: interactive, gate: taste` — видимое окно
   (`brain-council-tui`): иерархия, ритм, anti-slop, дайлы VARIANCE/MOTION/DENSITY
   с **dashboard-пресетом** (density high, motion low).
3. **designer** — primary, синтез по единому `uiux-reference`.
4. **reviewer** — на **другом провайдере** (декорреляция слепых пятен).
5. **product** — gate scope (anti-gold-plating).
6. **Человек — владелец gate** финализирует вердикт (особенно вкус).

## Разграничение ролей
| Роль | Слой | Surface | Владеет | НЕ делает |
|------|------|---------|---------|-----------|
| impeccable-reviewer | структура/детекторы | headless | контраст, bans, z-index, a11y, line-length | субъективный вкус |
| taste-reviewer | вкус/anti-slop | interactive/taste | иерархия, ритм, дайлы | не считает контраст |
| designer | синтез/дизайн-язык | interactive | tokens, итоговое решение | не утверждает в одиночку |
| reviewer | критика/декорреляция | headless (др. провайдер) | риски, корректность | не primary |
| product | scope-gate | interactive/intake | оправданность объёма | не дизайнит |
| developer | реализуемость | headless | интеграция детектора, surface-разметка | не выносит вкус-вердикт |

## Integration policy
- **Не устанавливать** внешние skill через `npx skills add` (write-gate/supply-chain).
- **Снапшот правил** в единый Brain `uiux-reference`: taste-skill (MIT) +
  impeccable detector-subset (Apache-2.0), сохранить attribution/NOTICE.
- Детектор: изолированный node ИЛИ порт top-правил в Python — по итогам PoC.
  Browser/visual движок — только advisory, не в обязательный gate.

## Связь с interactive-surface
Workflow плагинится в `surface`/`gate` (см.
`wiki/decision-interactive-surface.md`): impeccable-reviewer = headless,
taste-reviewer = interactive/taste. Эпик «человек в видимом окне» и эпик
design-review сомкнуты.
