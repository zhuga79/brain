#!/usr/bin/env bash
# case: prompt-budget — промпт собирается из ядра, роли и среза реестра
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying prompt structure and budget"

prompt="$(brain-run --role architect 2>/dev/null || true)"
[ -n "$prompt" ] || { echo "FAILED: brain-run ничего не выдал"; exit 1; }

# ── 1. Обязательные разделы на месте ──
for section in "=== SYSTEM ===" "=== ROLE: architect ===" "=== REGISTRY" "=== INSTRUCTIONS ==="; do
  grep -qF "$section" <<< "$prompt" || { echo "FAILED: нет раздела $section"; exit 1; }
done
echo "OK: обязательные разделы на месте"

# ── 2. Срез реестра — только про свою роль ──
grep -q 'Роль `architect`' <<< "$prompt" || { echo "FAILED: реестр не описывает роль"; exit 1; }
# Перечня всех ролей в промпте быть не должно: он рос при добавлении любой роли,
# а цену платил каждый запуск любого агента.
foreign=0
for role in accountant copywriter renovation-planner taste-reviewer; do
  grep -q "Роль \`$role\`" <<< "$prompt" && foreign=$((foreign + 1))
done
[ "$foreign" -eq 0 ] || { echo "FAILED: в промпт попал реестр чужих ролей"; exit 1; }
echo "OK: реестр обрезан по роли"

# ── 3. Размер печатается в stderr ──
size_line="$(brain-run --role architect 2>&1 >/dev/null | grep 'промпт' || true)"
[ -n "$size_line" ] || { echo "FAILED: размер промпта не сообщается"; exit 1; }
echo "OK: размер сообщается ($size_line)"

# ── 4. Бюджет ──
# Порог — защита от возврата к прежнему состоянию (было 28,9 КБ, из них 72%
# MEMORY.md), а не самоцель: резать обязательные правила ради числа нельзя.
# Меряем долю конституции, а не абсолютный размер: остальное — журнал, задача
# и рабочее пространство, они зависят от состояния фабрики, а не от вёрстки
# промпта. Смысл задачи был в том, что MEMORY.md занимала 72% каждого запуска.
printf '%s' "$prompt" | python3 -c "
import re, sys
text = sys.stdin.read()
total = len(text.encode())
memory = 0
for part in re.split(r'(?m)^# === ', text)[1:]:
    if part.startswith('MEMORY.md'):
        memory = len(part.encode())
share = memory / total if total else 0
print(f'  промпт {total} Б, из них MEMORY.md {memory} Б ({share:.0%})')
# Порог на саму конституцию: доля тут плохой измеритель — она растёт, когда
# уменьшаются журнал и индекс, то есть наказывает за улучшения.
assert memory <= 12000, f'MEMORY.md в промпте {memory} Б — реестры вернулись в конституцию'
" || exit 1
echo "OK: доля конституции в пределах"

# ── 5. Реестры не дублируются в MEMORY.md ──
grep -qE '^\| *`?(architect|developer)`? *\|' "$BRAIN_PATH/MEMORY.md" && {
  echo "FAILED: таблица ролей вернулась в MEMORY.md"
  exit 1
}
echo "OK: MEMORY.md не держит реестр ролей"

echo ">>> prompt budget checks passed"
