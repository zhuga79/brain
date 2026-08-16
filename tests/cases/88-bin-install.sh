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
  [ "$b" = "brain-mcp" ] && continue
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
capture_output _bs_drift 'brain-status'
grep -q 'CLI parity: status=drift' <<< "$_bs_drift" || {
  echo "FAILED: brain-status text output did not warn about CLI drift"
  exit 1
}
echo "OK: brain-status flags installed CLI drift"

rm -f "$HOME/.local/bin/brain-doctrine"
install -m 755 "$PROJECT_ROOT/runtime/bin/brain-doctrine" "$HOME/.local/bin/brain-doctrine"
brain-status --json | python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin)["cli_parity"]["status"]=="ok" else 1)' || {
  echo "FAILED: brain-status did not return to clean parity after restoring managed CLI"
  exit 1
}

cat > "$HOME/.local/bin/brain-legacy-extra" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$HOME/.local/bin/brain-legacy-extra"
brain-status --json | python3 -c 'import json,sys; d=json.load(sys.stdin)["cli_parity"]; names=[x["name"] for x in d.get("extras", [])]; raise SystemExit(0 if d["status"]=="drift" and "brain-legacy-extra" in names and d["drift_count"] > 0 else 1)' || {
  echo "FAILED: brain-status did not flag extra installed brain CLI absent from canonical source"
  exit 1
}
capture_output _bs_extra 'brain-status'
grep -q 'brain-legacy-extra' <<< "$_bs_extra" || {
  echo "FAILED: brain-status text output did not list extra installed brain CLI"
  exit 1
}
rm -f "$HOME/.local/bin/brain-legacy-extra"
brain-status --json | python3 -c 'import json,sys; d=json.load(sys.stdin)["cli_parity"]; raise SystemExit(0 if d["status"]=="ok" and not d.get("extras") else 1)' || {
  echo "FAILED: brain-status did not return to clean parity after removing extra installed brain CLI"
  exit 1
}
echo "OK: brain-status flags extra installed brain CLIs and returns clean after removal"

# Второй список неизбежно отстаёт от первого — поимённых установок быть не должно.
if grep -qE 'install -m 755 "\$RUNTIME_BRAIN_[A-Z_]+"' "$PROJECT_ROOT/add-power-features-brain.sh"; then
  echo "FAILED: add-power-features-brain.sh снова ставит команды поимённо"
  exit 1
fi
echo "OK: установка идёт из одного места"

echo ">>> bin install checks passed"
