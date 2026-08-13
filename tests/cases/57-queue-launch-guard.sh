#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying queue-proposal relaunch guard (only pending may launch)"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki" "$BRAIN_PATH/roles" "$BRAIN_PATH/.brain/launch-queue"
cat > "$BRAIN_PATH/tasks/active.md" <<'TASKS'
# Active Tasks
TASKS
cat > "$BRAIN_PATH/wiki/log.md" <<'LOG'
# Log
LOG
cat > "$BRAIN_PATH/roles/developer.md" <<'ROLE'
# Developer
ROLE

# A proposal that has already been launched must not be relaunched.
cat > "$BRAIN_PATH/.brain/launch-queue/proposals.json" <<'JSON'
{
  "ok": true,
  "generated_at": "2026-05-29T10:00:00Z",
  "summary": {"pending": 0},
  "proposals": [
    {
      "id": "qp-test-launched",
      "status": "launched",
      "launched_at": "2026-05-29T10:05:00Z",
      "task": "t-2026-05-29-already-launched",
      "title": "Already launched",
      "role": "developer",
      "client": "codex",
      "workspace": ""
    }
  ]
}
JSON

srv_pid=""
srv2_pid=""
shim_dir=""
cleanup() {
  [ -z "$srv_pid" ] || kill "$srv_pid" 2>/dev/null || true
  [ -z "$srv2_pid" ] || kill "$srv2_pid" 2>/dev/null || true
  [ -z "$shim_dir" ] || rm -rf "$shim_dir"
}
trap cleanup EXIT

BRAIN_SANDBOX_AGENT_LAUNCH_GUARD=1 brain-dashboard serve --port 19988 &
srv_pid=$!
sleep 1

# Live (non-dry-run) relaunch of a non-pending proposal must be rejected.
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST \
  "http://127.0.0.1:19988/api/queue-proposals/qp-test-launched/launch?dry_run=0" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is False, f'relaunch of launched proposal should fail: {d}'
assert d.get('status') == 'launched', f'expected status echoed back: {d}'
assert 'relaunch' in d.get('error','').lower(), f'expected relaunch guard error: {d}'
print('relaunch guard rejects non-pending live launch OK')
" || { echo "FAILED: relaunch guard did not reject"; exit 1; }

# Dry-run of the same proposal is still allowed (read-only preview).
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST \
  "http://127.0.0.1:19988/api/queue-proposals/qp-test-launched/launch?dry_run=1" | python3 -c "
import sys, json
d = json.load(sys.stdin)
# dry-run passes the guard; it may still fail later (sandbox/missing orchestrator),
# but it must NOT be rejected by the relaunch guard.
assert 'relaunch' not in d.get('error','').lower(), f'dry-run must bypass relaunch guard: {d}'
print('relaunch guard allows dry-run OK')
" || { echo "FAILED: dry-run wrongly blocked by relaunch guard"; exit 1; }

# Concurrent live POSTs for the same pending proposal must reserve it before
# spawning brain-orchestrator, so only one subprocess can start.
shim_dir="$(mktemp -d /tmp/brain-queue-race.XXXXXX)"
call_log="$BRAIN_FACTORY_TMP/queue-launch-calls.log"
cat > "$shim_dir/brain-orchestrator" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$BRAIN_FAKE_ORCHESTRATOR_CALLS"
sleep 2
exit 0
SH
chmod +x "$shim_dir/brain-orchestrator"
export PATH="$shim_dir:$PROJECT_ROOT/runtime/bin:$PATH"
export BRAIN_FAKE_ORCHESTRATOR_CALLS="$call_log"

cat > "$BRAIN_PATH/.brain/launch-queue/proposals.json" <<'JSON'
{
  "ok": true,
  "generated_at": "2026-06-01T10:00:00Z",
  "summary": {"pending": 1},
  "proposals": [
    {
      "id": "qp-race",
      "status": "pending",
      "task": "t-2026-06-01-race",
      "title": "Race launch",
      "role": "developer",
      "client": "codex",
      "workspace": ""
    }
  ]
}
JSON

env -u CODEX_SANDBOX_NETWORK_DISABLED -u CODEX_SANDBOX -u SANDBOX_MODE -u BRAIN_SANDBOX_AGENT_LAUNCH_GUARD \
  brain-dashboard serve --port 19996 &
srv2_pid=$!
sleep 1

curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST \
  "http://127.0.0.1:19996/api/queue-proposals/qp-race/launch?dry_run=0" > "$BRAIN_FACTORY_TMP/race-1.json" &
pid1=$!
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST \
  "http://127.0.0.1:19996/api/queue-proposals/qp-race/launch?dry_run=0" > "$BRAIN_FACTORY_TMP/race-2.json" &
pid2=$!
wait "$pid1"
wait "$pid2"

call_count=$(wc -l < "$call_log" | tr -d ' ')
[ "$call_count" = "1" ] || {
  echo "FAILED: expected exactly one orchestrator call, got $call_count"
  cat "$BRAIN_FACTORY_TMP/race-1.json" "$BRAIN_FACTORY_TMP/race-2.json"
  exit 1
}

python3 - "$BRAIN_PATH/.brain/launch-queue/proposals.json" "$BRAIN_FACTORY_TMP/race-1.json" "$BRAIN_FACTORY_TMP/race-2.json" <<'PY'
import json, sys
queue_path, first_path, second_path = sys.argv[1:]
responses = [json.load(open(first_path)), json.load(open(second_path))]
assert sum(1 for item in responses if item.get("ok") is True) == 1, responses
blocked = [item for item in responses if item.get("ok") is False]
assert len(blocked) == 1, responses
assert blocked[0].get("status") in {"launching", "launched"}, responses
assert "relaunch" in blocked[0].get("error", "").lower(), responses
queue = json.load(open(queue_path))
proposal = queue["proposals"][0]
assert proposal["status"] == "launched", proposal
assert proposal.get("launching_at"), proposal
assert proposal.get("launched_at"), proposal
print("concurrent queue proposal launch starts only one subprocess OK")
PY

echo ">>> queue-launch-guard checks passed"
