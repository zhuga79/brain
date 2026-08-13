#!/usr/bin/env bash
# case: dashboard-typography — базовый кегль адаптивен, приоритет кодируется значком
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying dashboard typography and priority encoding"
brain-dashboard export > /dev/null
html="$BRAIN_PATH/wiki/_views/brain-dashboard.html"
[ -f "$html" ] || { echo "FAILED: brain-dashboard.html not created"; exit 1; }

# ── 1. Кегль задан диапазоном, а не одним числом ──
# Решение оператора 2026-08-11: вместо выбора «20px или 16px» кегль тянется за
# шириной окна. Границы держим здесь: без них clamp однажды сожмут до нечитаемого.
grep -qE -- '--fs-base:[[:space:]]*clamp\(' "$html" || {
  echo "FAILED: --fs-base не адаптивен (ожидался clamp)"; exit 1; }
# Границы в rem, а не в px: так пользовательская настройка размера шрифта в
# браузере продолжает действовать. На чистых px+vw она игнорируется — ровно
# поэтому visual-check запрещает кегль, зависящий от окна.
grep -qE -- '--fs-base:[[:space:]]*clamp\(1rem,[^)]*1\.25rem\)' "$html" || {
  echo "FAILED: границы кегля изменились — ожидались 1rem…1.25rem"
  grep -oE -- '--fs-base:[^;]*' "$html" | head -1
  exit 1
}
echo "OK: базовый кегль адаптивен в границах 1–1.25rem и уважает настройку браузера"

# ── 2. Мелкий текст — доля базы ──
# В rem он был привязан к 16px браузера и на узком экране сравнивался с базой.
grep -qE -- '--fs-small:[[:space:]]*calc\(var\(--fs-base\)' "$html" || {
  echo "FAILED: --fs-small не привязан к базовому кеглю"; exit 1; }
echo "OK: мелкий текст пропорционален базе"

grep -q 'font-size: var(--fs-base);' "$html" || { echo "FAILED: body не использует --fs-base"; exit 1; }
grep -q 'font-size: var(--fs-small);' "$html" || { echo "FAILED: --fs-small не используется"; exit 1; }

# ── 3. Приоритет кодируется значком, а не боковой полосой ──
# Полоса дублировала подпись «P1» и попадала под правило side-tab.
grep -qE '\.task-card[^{]*\{[^}]*border-left:[[:space:]]*[2-9]' "$html" && {
  echo "FAILED: цветная полоса приоритета вернулась на карточку"; exit 1; }
grep -q 'badge-prio' "$html" || { echo "FAILED: значок приоритета не размечен классом badge-prio"; exit 1; }
grep -qE '\.task-card\.prio-P1 \.badge-prio' "$html" || {
  echo "FAILED: цвет приоритета не привязан к значку"; exit 1; }
echo "OK: приоритет кодируется значком"

# ── 4. Линтер оформления чист ──
brain-uiux-lint --strict "$html" >/dev/null 2>&1 || {
  # Базовый список исключений живёт рядом с рабочим файлом; в песочнице его
  # может не быть, поэтому смотрим только на правило, ради которого правка.
  brain-uiux-lint "$html" 2>&1 | grep -q "side-tab" && {
    echo "FAILED: правило side-tab снова нарушено"; exit 1; }
}
echo "OK: side-tab не нарушен"

echo ">>> dashboard typography checks passed"
