#!/usr/bin/env bash
# case: install-idempotency — установка не правит системный слой как побочный эффект
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying installers do not rewrite the system layer"

brain_factory
bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1

# Снимок после первой установки: повторный запуск не должен ничего менять.
before="$BRAIN_FACTORY_TMP/before"
mkdir -p "$before"
for f in MEMORY.md tasks/SCHEMA.md .gitignore; do
  [ -f "$BRAIN_PATH/$f" ] && cp "$BRAIN_PATH/$f" "$before/$(basename "$f")"
done

for s in add-teams-brain.sh add-pm-finance-brain.sh add-design-negotiator-brain.sh \
         refine-tax-boundaries.sh add-power-features-brain.sh; do
  bash "$PROJECT_ROOT/$s" >/dev/null 2>&1 || true
done

changed=""
for f in MEMORY.md tasks/SCHEMA.md .gitignore; do
  b="$before/$(basename "$f")"
  [ -f "$b" ] || continue
  cmp -s "$b" "$BRAIN_PATH/$f" || changed="$changed $f"
done
[ -z "$changed" ] || {
  echo "FAILED: модульные скрипты переписали системные файлы:$changed"
  for f in $changed; do diff "$before/$(basename "$f")" "$BRAIN_PATH/$f" | head -10; done
  exit 1
}
echo "OK: MEMORY.md, SCHEMA.md и .gitignore не меняются установкой модулей"

# Реестры не возвращаются в конституцию.
grep -qE '^\| *`?architect`? *\|' "$BRAIN_PATH/MEMORY.md" && {
  echo "FAILED: таблица ролей вернулась в MEMORY.md после установки модулей"
  exit 1
}
echo "OK: реестры остались вне конституции"

# Схема задач — одна на всю систему.
if grep -q 'cat > "\$BRAIN/tasks/SCHEMA.md"' "$PROJECT_ROOT/add-power-features-brain.sh"; then
  echo "FAILED: вторая копия SCHEMA.md вернулась в add-power-features"
  exit 1
fi
echo "OK: схема задач имеет один источник"

echo ">>> install idempotency checks passed"
