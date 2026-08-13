---
title: Brain UI/UX Reference (taste + impeccable)
type: concept
created: 2026-06-29
updated: 2026-06-29
curation: agent
protected: false
source_policy: advisory
tags: [uiux, design-review, taste, impeccable, reference]
sources: []
related: [decision-interactive-surface]
visibility: public
---

# Brain UI/UX Reference

Единый источник UI-правил для Brain, сведённый из двух ADAPT-ревью:
`taste-skill` (вкус, MIT) и `impeccable` (структура/детекторы, Apache-2.0).
Рабочий процесс применения — `doctrine/design-review-workflow.md`.
Детерминированное подмножество **энфорсится** `brain-uiux-lint` (pre-commit).

Для дата-плотных экранов смотри также шаблон
`runtime/templates/v2/skills/uiux/brain/data-dense-dashboard-design.md`
(information architecture экранов очередей/таблиц)
— этот reference задаёт визуальный язык, тот шаблон — структуру экрана.

## Слой 1 — Вкус (из taste-skill, ADAPT)

### Anti-default дисциплина (чего избегать)
LLM-клише, помечай-и-переписывай: AI-purple градиенты, центр-hero на тёмном
mesh, три одинаковые feature-карточки, generic glassmorphism, бесконечные
micro-loop анимации, Inter + slate-900 по умолчанию.

### Три дайла (осознанные оси вместо «сделай красиво»)
`DESIGN_VARIANCE / MOTION_INTENSITY / VISUAL_DENSITY`.
**Dashboard-пресет Brain (инверсия лендинговому):**
`VARIANCE 3-5 · MOTION 2-3 · DENSITY 6-8` — плотно, спокойно, предсказуемо.

### Типографика и иконки
- Иерархия размер/вес, `max-width ~65ch` для текстовых блоков.
- Одно семейство иконок, единый `stroke-width`, не рисовать SVG руками.

### Honesty-rule
Не выдавать неофициальное за официальное; не импортировать токены системы,
переопределяя 90% из них.

## Слой 2 — Структура / a11y (из impeccable, ADAPT + детекторы)

### Контраст (a11y, энфорсится)
Body ≥ 4.5:1, large (≥18px / bold ≥14px) ≥ 3:1, placeholder 4.5:1.
Светло-серый текст «для элегантности» — главная причина нечитаемости.

### Absolute bans (match-and-refuse, частично энфорсится)
- **Side-stripe borders** (`border-left/right` >1px как цветной акцент) →
  полная граница / фон-тинт / ведущая иконка-число / ничего.
- **Gradient text** (`background-clip:text` + gradient) → один сплошной цвет.
- **Glassmorphism по умолчанию**, **hero-metric template**,
  **identical card grids**, **uppercase tracked eyebrow на каждой секции**,
  **numbered section markers как scaffolding**, **text-overflow контейнера**.

### Layout / motion
- Semantic z-index scale (dropdown→sticky→modal→toast→tooltip); без 999/9999.
- Flex для 1D, Grid для 2D; адаптивная сетка `repeat(auto-fit, minmax(280px,1fr))`.
- Cards — ленивый ответ; вложенные карточки всегда неверны.
- `prefers-reduced-motion` обязателен; reveal усиливает уже видимый дефолт
  (не гейтить контент классом-переходом).
- Display letter-spacing floor ≥ -0.04em; display line-height tight — ок для
  крупных цифр/заголовков, не для body.

### Color discipline (advisory)
OKLCH; color-strategy axis: Restrained / Committed / Full-palette / Drenched.
«cream/sand/beige body bg» — насыщенный AI-дефолт 2026, избегать.

## Энфорсмент — `brain-uiux-lint`
Zero-dep Python-порт high-signal подмножества (выбран PoC над node-toolchain 739МБ):
`side-tab`, `single-font`, `tight-leading`, `low-contrast`. Advisory + `--strict`
(в pre-commit). Намеренные исключения — в `wiki/_views/uiux-lint-baseline.json`
с причиной. Шумовые правила (`design-system-color`, `em-dash`, `numbered-markers`)
отключены by default. Полный node-детектор impeccable — опциональный manual-инструмент.

## Attribution
- Вкус-слой портирован из **taste-skill** (github.com/Leonxlnx/taste-skill, MIT).
- Структура/детектор-слой портирован из **impeccable**
  (github.com/pbakaus/impeccable, Apache-2.0) — сохранять NOTICE при вендоринге кода.
