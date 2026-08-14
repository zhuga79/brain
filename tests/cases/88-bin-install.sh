#!/usr/bin/env bash
# case: bin-install — установка не пропускает ни одной команды
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying every runtime/bin command gets installed"

brain_factory
bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1
export BRAIN_SYSTEM_PATH="$PROJECT_ROOT"

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
brain-status --json | python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin)["cli_parity"]["status"]=="ok" else 1)' || {
  echo "FAILED: brain-status does not report clean CLI parity after install"
  exit 1
}
echo "OK: brain-status reports clean CLI parity after install"

printf '\n# drift probe\n' >> "$HOME/.local/bin/brain-doctrine"
brain-status --json | python3 -c 'import json,sys; d=json.load(sys.stdin)["cli_parity"]; names=[x["name"] for x in d["mismatches"]+d["missing"]]; raise SystemExit(0 if "brain-doctrine" in names else 1)' || {
  echo "FAILED: brain-status did not flag drifted installed CLI"
  exit 1
}
brain-status | grep -q 'CLI parity: status=drift' || {
  echo "FAILED: brain-status text output did not warn about CLI drift"
  exit 1
}
echo "OK: brain-status flags installed CLI drift"

# Второй список неизбежно отстаёт от первого — поимённых установок быть не должно.
if grep -qE 'install -m 755 "\$RUNTIME_BRAIN_[A-Z_]+"' "$PROJECT_ROOT/add-power-features-brain.sh"; then
  echo "FAILED: add-power-features-brain.sh снова ставит команды поимённо"
  exit 1
fi
echo "OK: установка идёт из одного места"

echo ">>> bin install checks passed"
