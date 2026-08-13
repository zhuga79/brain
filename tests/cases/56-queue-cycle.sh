#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying daily queue-cycle dashboard confirmation flow"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki" "$BRAIN_PATH/roles"
cat > "$BRAIN_PATH/tasks/active.md" <<'EOF'
# Active Tasks

- [ ] [P1] t-2026-05-29-ready-dev — Ready developer task
      role: developer   mode: solo
      acceptance: Dry-run launch proposal is generated.

- [ ] [P1] t-2026-05-29-needs-formalization — Needs task formalization
      role: product   mode: solo
      acceptance: TODO
EOF
cat > "$BRAIN_PATH/tasks/done.md" <<'EOF'
# Done Tasks
EOF
cat > "$BRAIN_PATH/wiki/log.md" <<'EOF'
# Log
EOF
cat > "$BRAIN_PATH/wiki/index.md" <<'EOF'
# Wiki Index
EOF
cat > "$BRAIN_PATH/roles/developer.md" <<'EOF'
# Developer
EOF
cat > "$BRAIN_PATH/roles/product.md" <<'EOF'
# Product
EOF

brain-queue-cycle --brain "$BRAIN_PATH" --apply --json > "$BRAIN_FACTORY_TMP/queue-cycle.json"
grep -q '"mode": "apply"' "$BRAIN_FACTORY_TMP/queue-cycle.json" || {
  echo "FAILED: queue-cycle apply did not emit JSON"
  cat "$BRAIN_FACTORY_TMP/queue-cycle.json"
  exit 1
}
test -f "$BRAIN_PATH/.brain/launch-queue/proposals.json" || {
  echo "FAILED: proposals.json missing"
  exit 1
}
proposal_id=$(python3 - "$BRAIN_PATH/.brain/launch-queue/proposals.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
items = data.get("proposals", [])
assert items, data
assert items[0]["status"] == "pending", items[0]
assert items[0]["task"] == "t-2026-05-29-ready-dev", items[0]
assert items[0]["role"] == "developer", items[0]
assert items[0]["client"] in {"codex", "claude", "gemini", "ollama", "opencode", "kilocode"}, items[0]
assert "workspace" in items[0], items[0]
assert items[0].get("scope") in {"global", "workspace"}, items[0]
print(items[0]["id"])
PY
)
[ -n "$proposal_id" ] || { echo "FAILED: proposal id empty"; exit 1; }
grep -q "Queue corrective: formalize tasks before launch" "$BRAIN_PATH/tasks/active.md" || {
  echo "FAILED: queue-cycle did not add formalization corrective task"
  cat "$BRAIN_PATH/tasks/active.md"
  exit 1
}
before_count=$(grep -c "Queue corrective: formalize tasks before launch" "$BRAIN_PATH/tasks/active.md")
brain-queue-cycle --brain "$BRAIN_PATH" --apply --json > "$BRAIN_FACTORY_TMP/queue-cycle-2.json"
after_count=$(grep -c "Queue corrective: formalize tasks before launch" "$BRAIN_PATH/tasks/active.md")
[ "$before_count" = "$after_count" ] || {
  echo "FAILED: queue-cycle duplicated formalization task"
  cat "$BRAIN_PATH/tasks/active.md"
  exit 1
}

brain-dashboard export --out "$BRAIN_FACTORY_TMP/dashboard.html" >/dev/null
# Редизайн 73f18f2 растворил отдельную секцию автопилота: предложение теперь
# висит на карточке самой задачи. Проверяем привязку, а не бывший id секции.
grep -q 'data-kb-proposal' "$BRAIN_FACTORY_TMP/dashboard.html" || {
  echo "FAILED: dashboard missing proposal binding on task cards"
  exit 1
}
grep -q "$proposal_id" "$BRAIN_FACTORY_TMP/dashboard.html" || {
  echo "FAILED: dashboard missing proposal id"
  exit 1
}
grep -q "/api/queue-proposals" "$BRAIN_FACTORY_TMP/dashboard.html" || {
  echo "FAILED: dashboard missing proposal API wiring"
  exit 1
}

srv_pid=""
cleanup_srv() {
  if [ -n "$srv_pid" ]; then
    kill "$srv_pid" 2>/dev/null || true
    wait "$srv_pid" 2>/dev/null || true
    srv_pid=""
  fi
}
trap cleanup_srv EXIT

BRAIN_SANDBOX_AGENT_LAUNCH_GUARD=1 brain-dashboard serve --port 19989 &
srv_pid=$!
sleep 1

queue_api_json="$BRAIN_FACTORY_TMP/queue-proposals-api.json"
curl -s --noproxy '*' "http://127.0.0.1:19989/api/queue-proposals" > "$queue_api_json"
python3 - "$proposal_id" "$queue_api_json" <<'PY'
import json, sys
expected = sys.argv[1]
data = json.load(open(sys.argv[2]))
assert data.get("ok") is True, data
ids = [item["id"] for item in data.get("proposals", [])]
assert expected in ids, data
print("GET /api/queue-proposals OK")
PY

post_guard_json="$BRAIN_FACTORY_TMP/queue-proposal-post-guard.json"
curl -s --noproxy '*' -X POST "http://127.0.0.1:19989/api/queue-proposals/$proposal_id/launch?dry_run=1" > "$post_guard_json"
python3 - "$post_guard_json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
assert data.get("ok") is False, data
assert "X-Brain-Confirm" in data.get("error", ""), data
print("POST proposal launch CSRF guard OK")
PY

post_dry_run_json="$BRAIN_FACTORY_TMP/queue-proposal-post-dry-run.json"
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:19989/api/queue-proposals/$proposal_id/launch?dry_run=1" > "$post_dry_run_json"
python3 - "$post_dry_run_json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
assert data.get("ok") is True, data
assert data.get("proposal"), data
assert data.get("dry_run") is True, data
assert "DRY-RUN: operator console plan" in data.get("output", ""), data
print("POST proposal dry-run OK")
PY

post_live_json="$BRAIN_FACTORY_TMP/queue-proposal-post-live.json"
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:19989/api/queue-proposals/$proposal_id/launch" > "$post_live_json"
python3 - "$post_live_json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
assert data.get("ok") is False, data
assert data.get("sandbox_blocked") is True, data
assert "sandbox" in data.get("error", "").lower(), data
print("POST proposal live sandbox guard OK")
PY

cleanup_srv
trap - EXIT

unit_dir="$BRAIN_FACTORY_TMP/systemd-user"
brain-queue-cycle install-systemd --brain "$BRAIN_PATH" --unit-dir "$unit_dir" --no-enable --json > "$BRAIN_FACTORY_TMP/install.json"
test -f "$unit_dir/brain-queue-cycle.service" || { echo "FAILED: service unit missing"; exit 1; }
test -f "$unit_dir/brain-queue-cycle.timer" || { echo "FAILED: timer unit missing"; exit 1; }
grep -q "OnCalendar=daily" "$unit_dir/brain-queue-cycle.timer" || {
  echo "FAILED: queue-cycle timer is not daily"
  cat "$unit_dir/brain-queue-cycle.timer"
  exit 1
}
grep -q -- "--apply" "$unit_dir/brain-queue-cycle.service" || {
  echo "FAILED: queue-cycle service does not apply proposals"
  cat "$unit_dir/brain-queue-cycle.service"
  exit 1
}
! grep -q -- "--launch" "$unit_dir/brain-queue-cycle.service" || {
  echo "FAILED: queue-cycle timer must not live launch agents"
  cat "$unit_dir/brain-queue-cycle.service"
  exit 1
}

echo "daily queue-cycle dashboard confirmation OK"
