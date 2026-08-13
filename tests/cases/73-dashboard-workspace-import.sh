#!/usr/bin/env bash
# Test: /api/workspace/import endpoint — auth gate + SSRF guard + local descriptor.
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying /api/workspace/import (auth + SSRF guard + local file)"
brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki"
printf '# Active Tasks\n' > "$BRAIN_PATH/tasks/active.md"
printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"

brain-dashboard serve --port 19996 &
srv_pid=$!
trap 'kill $srv_pid 2>/dev/null || true' EXIT
sleep 1

# missing confirm header -> rejected (CSRF gate)
curl -s --noproxy '*' -X POST "http://127.0.0.1:19996/api/workspace/import?descriptor=/tmp/x" | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert d.get('ok') is False and 'Confirm' in d.get('error',''), f'confirm gate: {d}'
print('OK: confirm gate')" || { echo "FAILED: confirm gate"; exit 1; }

# SSRF: private/loopback URL -> rejected
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:19996/api/workspace/import?descriptor=http://127.0.0.1/x" | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert d.get('ok') is False and 'reject' in d.get('error','').lower(), f'SSRF guard: {d}'
print('OK: SSRF guard blocks loopback URL')" || { echo "FAILED: SSRF guard"; exit 1; }

# valid local descriptor -> parsed and applied to a target folder
cat > "$BRAIN_FACTORY_TMP/desc.json" <<'JSON'
{"name":"Demo Project","goal":"Test import","tasks":["Сделать A","Сделать B"],"roles":["developer"]}
JSON
target_dir="$BRAIN_FACTORY_TMP/demo-workspace"
mkdir -p "$target_dir"
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:19996/api/workspace/import?descriptor=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$BRAIN_FACTORY_TMP/desc.json")&target=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$target_dir")" | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert d.get('ok') is True and d.get('name')=='Demo Project', f'local import: {d}'
assert d.get('workspace') and d.get('created_tasks') == 2, f'applied workspace import: {d}'
print('OK: local descriptor applied to target workspace')" || { echo "FAILED: local descriptor"; exit 1; }
grep -q "# Demo Project" "$target_dir/BRAIN.md" || { echo "FAILED: BRAIN.md not created from descriptor"; exit 1; }
grep -q "Сделать A" "$target_dir/TASKS.md" || { echo "FAILED: TASKS.md missing imported task"; exit 1; }

# local descriptor without target -> apply to the descriptor's parent folder
inferred_dir="$BRAIN_FACTORY_TMP/inferred-workspace"
mkdir -p "$inferred_dir"
cat > "$inferred_dir/project.json" <<'JSON'
{"name":"Inferred Workspace","goal":"Use descriptor parent","tasks":["Task from parent"],"roles":["pm"]}
JSON
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:19996/api/workspace/import?descriptor=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$inferred_dir/project.json")" | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert d.get('ok') is True and d.get('workspace','').endswith('inferred-workspace'), f'inferred target: {d}'
assert d.get('created_tasks') == 1, d
print('OK: local descriptor parent used as target')" || { echo "FAILED: inferred local target"; exit 1; }

# UI: import field + button present on the page
page="$(curl -s --noproxy '*' "http://127.0.0.1:19996/")"
grep -q 'id="ws-import-btn"' <<< "$page" || { echo "FAILED: import UI button missing"; exit 1; }
grep -q 'id="ws-import-desc"' <<< "$page" || { echo "FAILED: import UI input missing"; exit 1; }
grep -q 'id="ws-import-target"' <<< "$page" || { echo "FAILED: import target input missing"; exit 1; }
echo "OK: import UI rendered"

echo ">>> workspace-import checks passed"
