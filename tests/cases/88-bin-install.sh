#!/usr/bin/env bash
# case: bin-install — установка не пропускает ни одной команды
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying every runtime/bin command gets installed"

brain_factory
bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1

missing=""
count=0
for f in "$PROJECT_ROOT"/runtime/bin/*; do
  [ -f "$f" ] || continue
  b="$(basename "$f")"
  count=$((count + 1))
  if [ ! -x "$HOME/.local/bin/$b" ]; then
    missing="$missing $b"
    continue
  fi
  # Установленная копия должна совпадать с деревом: расхождение означает,
  # что правка не действует, а понять это можно только по симптомам.
  cmp -s "$f" "$HOME/.local/bin/$b" || missing="$missing $b(stale)"
done

[ "$count" -gt 0 ] || { echo "FAILED: в runtime/bin нет файлов"; exit 1; }
[ -z "$missing" ] || {
  echo "FAILED: не установлены или устарели:$missing"
  exit 1
}
echo "OK: установлены и совпадают с деревом все $count команд"

# Второй список неизбежно отстаёт от первого — поимённых установок быть не должно.
if grep -qE 'install -m 755 "\$RUNTIME_BRAIN_[A-Z_]+"' "$PROJECT_ROOT/add-power-features-brain.sh"; then
  echo "FAILED: add-power-features-brain.sh снова ставит команды поимённо"
  exit 1
fi
echo "OK: установка идёт из одного места"

echo ">>> bin install checks passed"
