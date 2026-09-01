#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying shared allowed-clients list and workspace validation"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
export PYTHONPATH="$PROJECT_ROOT/runtime/lib"

# Single source of truth: both scripts derive clients from brain_launch_queue.
python3 - <<'PY'
import brain_launch_queue as q
assert isinstance(q.ALLOWED_CLIENTS, tuple) and "codex" in q.ALLOWED_CLIENTS, q.ALLOWED_CLIENTS
print("shared ALLOWED_CLIENTS present:", q.ALLOWED_CLIENTS)
PY
grep -q "brain_launch_queue.ALLOWED_CLIENTS" "$PROJECT_ROOT/runtime/bin/brain-dashboard" \
  || { echo "FAILED: brain-dashboard does not use shared ALLOWED_CLIENTS"; exit 1; }
# Логика queue-cycle живёт в brain_app.cycles.queue, CLI — фасад над ней.
grep -q "brain_launch_queue.ALLOWED_CLIENTS" "$PROJECT_ROOT/runtime/lib/brain_app/cycles/queue.py" \
  || { echo "FAILED: brain-queue-cycle does not use shared ALLOWED_CLIENTS"; exit 1; }
# Old hard-coded literal sets must be gone.
grep -q '"claude": "claude"' "$PROJECT_ROOT/runtime/bin/brain-dashboard" \
  && { echo "FAILED: brain-dashboard still hard-codes client map"; exit 1; }
echo "allowed-clients single source of truth OK"

mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki" "$BRAIN_PATH/roles" "$BRAIN_PATH/.brain/launch-queue"
printf '# Active Tasks\n' > "$BRAIN_PATH/tasks/active.md"
printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"
printf '# Developer\n' > "$BRAIN_PATH/roles/developer.md"
# Proposal whose workspace does not exist -> must be rejected before launch.
cat > "$BRAIN_PATH/.brain/launch-queue/proposals.json" <<'JSON'
{
  "ok": true,
  "proposals": [
    {"id": "qp-badws", "status": "pending", "task": "t-2026-05-29-badws", "title": "Bad workspace",
     "role": "developer", "client": "codex", "workspace": "/nonexistent/brain/workspace-xyz"}
  ]
}
JSON

port=$(pick_free_port)
brain-dashboard serve --port "$port" &
srv_pid=$!
trap 'kill $srv_pid 2>/dev/null || true' EXIT
wait_dashboard_port "$port"

curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST \
  "http://127.0.0.1:$port/api/queue-proposals/qp-badws/launch?dry_run=0" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is False, f'launch with bad workspace should fail: {d}'
assert 'workspace' in d.get('error','').lower(), f'expected workspace error: {d}'
print('invalid workspace rejected OK')
" || { echo "FAILED: invalid workspace not rejected"; exit 1; }

echo ">>> clients + workspace validation checks passed"
