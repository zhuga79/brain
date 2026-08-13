#!/usr/bin/env bash
# case: dashboard-visual-check
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-dashboard visual-check"

out_dir="/tmp/brain-dashboard-visual-smoke"
rm -rf "$out_dir"

brain-dashboard visual-check --out-dir "$out_dir" --json > /tmp/dashboard_visual_check.json

python3 - <<PY
import json
from pathlib import Path
data = json.load(open("/tmp/dashboard_visual_check.json"))
assert data["ok"] is True, data
assert Path(data["html"]).exists(), data
assert Path("$out_dir/visual-check.json").exists()
assert data["browser"] in ("ok", "skipped")
PY

grep -q 'id="operator-console"' "$out_dir/brain-dashboard.html" || {
  echo "FAILED: visual-check HTML missing operator-console section"
  exit 1
}
grep -q 'id="task-operations"' "$out_dir/brain-dashboard.html" || {
  echo "FAILED: visual-check HTML missing tasks section"
  exit 1
}

if python3 - <<'PY'
import json
raise SystemExit(0 if json.load(open("/tmp/dashboard_visual_check.json")).get("browser") == "ok" else 1)
PY
then
  [ -f "$out_dir/dashboard-desktop.png" ] || { echo "FAILED: missing desktop screenshot"; exit 1; }
  [ -f "$out_dir/dashboard-mobile.png" ] || { echo "FAILED: missing mobile screenshot"; exit 1; }
fi

echo "dashboard-visual-check OK"
