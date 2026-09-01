#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-dashboard POST actions"
grep -q "def do_POST" "$PROJECT_ROOT/runtime/bin/brain-dashboard" || { echo "FAILED: do_POST missing from brain-dashboard"; exit 1; }
grep -q '"take"' "$PROJECT_ROOT/runtime/bin/brain-dashboard" || { echo "FAILED: take action missing"; exit 1; }
grep -q '"release"' "$PROJECT_ROOT/runtime/bin/brain-dashboard" || { echo "FAILED: release action missing"; exit 1; }
grep -q '"complete"' "$PROJECT_ROOT/runtime/bin/brain-dashboard" || { echo "FAILED: complete action missing"; exit 1; }
grep -q '"block"' "$PROJECT_ROOT/runtime/bin/brain-dashboard" || { echo "FAILED: block action missing"; exit 1; }
grep -q 'api/launch' "$PROJECT_ROOT/runtime/bin/brain-dashboard" || { echo "FAILED: launch endpoint missing"; exit 1; }

# Live HTTP POST test: full take→complete lifecycle + error cases
brain-task add "Smoke POST take" --role developer --prio P1 > /dev/null
post_task_id=$(grep "Smoke POST take" "$BRAIN_PATH/tasks/active.md" | grep -oE "t-[0-9-]+-smoke-post-take" | head -1)
[ -n "$post_task_id" ] || { echo "FAILED: could not create task for POST test"; exit 1; }
post_port=$(pick_free_port)
BRAIN_SANDBOX_AGENT_LAUNCH_GUARD=1 brain-dashboard serve --port "$post_port" &
srv_pid=$!
wait_dashboard_port "$post_port"

# POST without dashboard confirmation header must be rejected (CSRF guard)
curl -s --noproxy '*' -X POST "http://127.0.0.1:$post_port/api/tasks/$post_task_id?as=smoke-agent&action=take" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is False, f'POST without confirm header should fail: {d}'
assert 'X-Brain-Confirm' in d.get('error',''), f'Missing CSRF guard error: {d}'
print('POST /api/tasks CSRF guard OK')
" || { kill $srv_pid 2>/dev/null; echo "FAILED: POST without confirm header not rejected"; exit 1; }

# POST take
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:$post_port/api/tasks/$post_task_id?as=smoke-agent&action=take" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is True, f'POST take failed: {d}'
print('POST /api/tasks take OK')
" || { kill $srv_pid 2>/dev/null; echo "FAILED: POST take failed"; exit 1; }
[ -f "$BRAIN_PATH/.locks/$post_task_id/owner" ] || { kill $srv_pid 2>/dev/null; echo "FAILED: lock not created by POST take"; exit 1; }

# POST complete (task must be taken first)
log_lines_before=$(wc -l < "$BRAIN_PATH/wiki/log.md")
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:$post_port/api/tasks/$post_task_id?as=smoke-agent&action=complete" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is True, f'POST complete failed: {d}'
print('POST /api/tasks complete OK')
" || { kill $srv_pid 2>/dev/null; echo "FAILED: POST complete failed"; exit 1; }
# Lock should be released after complete
[ ! -f "$BRAIN_PATH/.locks/$post_task_id/owner" ] || { kill $srv_pid 2>/dev/null; echo "FAILED: lock still exists after POST complete"; exit 1; }
# Task should appear in done.md
grep -q "$post_task_id" "$BRAIN_PATH/tasks/done.md" || { kill $srv_pid 2>/dev/null; echo "FAILED: completed task not in done.md"; exit 1; }
# Log should have grown
log_lines_after=$(wc -l < "$BRAIN_PATH/wiki/log.md")
[ "$log_lines_after" -gt "$log_lines_before" ] || { kill $srv_pid 2>/dev/null; echo "FAILED: log.md not updated after POST complete"; exit 1; }

# POST unknown action → 400
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:$post_port/api/tasks/$post_task_id?as=smoke-agent&action=destroy" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is False, f'Unknown action should have failed: {d}'
assert 'unknown action' in d.get('error',''), f'Missing error message: {d}'
print('POST unknown action → 400 OK')
" || { kill $srv_pid 2>/dev/null; echo "FAILED: unknown action not rejected"; exit 1; }

# POST missing ?as → 400
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:$post_port/api/tasks/$post_task_id" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is False, f'Missing as should have failed: {d}'
print('POST missing ?as → 400 OK')
" || { kill $srv_pid 2>/dev/null; echo "FAILED: missing ?as not rejected"; exit 1; }

brain-task add "Smoke POST block" --role developer --prio P1 > /dev/null
block_task_id=$(grep "Smoke POST block" "$BRAIN_PATH/tasks/active.md" | grep -oE "t-[0-9-]+-smoke-post-block" | head -1)
[ -n "$block_task_id" ] || { kill $srv_pid 2>/dev/null; echo "FAILED: could not create task for POST block test"; exit 1; }
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:$post_port/api/tasks/$block_task_id?as=smoke-agent&action=block&reason=smoke-block" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is True, f'POST block failed: {d}'
print('POST /api/tasks block OK')
" || { kill $srv_pid 2>/dev/null; echo "FAILED: POST block failed"; exit 1; }
grep -q "^- \\[!\\].*$block_task_id" "$BRAIN_PATH/tasks/active.md" || { kill $srv_pid 2>/dev/null; echo "FAILED: blocked task not marked [!]"; exit 1; }

workspace_root="$(mktemp -d /tmp/brain-dashboard-launch-workspace.XXXXXX)"
mkdir -p "$workspace_root"
cat > "$workspace_root/BRAIN.md" <<'EOF'
# Workspace: Dashboard Launch

## Role Policy

available:
- lawyer
EOF
cat > "$workspace_root/TASKS.md" <<'EOF'
# Local Tasks

- [ ] [P1] local-001 - Review local draft
      role: lawyer
      acceptance: launch plan generated.
EOF
mkdir -p "$BRAIN_PATH/roles"
cat > "$BRAIN_PATH/roles/lawyer.md" <<'EOF'
# Lawyer
EOF

curl -s --noproxy '*' -X POST "http://127.0.0.1:$post_port/api/launch?workspace=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$workspace_root")&task=local-001&role=lawyer&client=codex&dry_run=1" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is False, f'launch without confirm should fail: {d}'
assert 'X-Brain-Confirm' in d.get('error',''), f'Missing CSRF guard error: {d}'
print('POST /api/launch CSRF guard OK')
" || { kill $srv_pid 2>/dev/null; echo "FAILED: launch without confirm not rejected"; exit 1; }

curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:$post_port/api/launch?workspace=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$workspace_root")&task=local-001&role=lawyer&client=badcli&dry_run=1" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is False, f'bad client should fail: {d}'
assert 'client' in d.get('error','').lower(), f'Missing client error: {d}'
print('POST /api/launch bad client rejected OK')
" || { kill $srv_pid 2>/dev/null; echo "FAILED: launch bad client not rejected"; exit 1; }

curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:$post_port/api/launch?workspace=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$workspace_root")&task=local-001&role=lawyer&client=codex&dry_run=1" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is True, f'launch dry-run failed: {d}'
assert d.get('task') == 'local-001', d
assert d.get('role') == 'lawyer', d
assert d.get('client') == 'codex', d
assert 'DRY-RUN: operator console plan' in d.get('output',''), d
assert 'local-001' in d.get('output',''), d
assert 'Dashboard Launch' in d.get('output','') or 'workspace' in d.get('output',''), d
print('POST /api/launch dry-run OK')
" || { kill $srv_pid 2>/dev/null; echo "FAILED: launch dry-run failed"; exit 1; }

curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:$post_port/api/launch?workspace=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$workspace_root")&task=local-001&role=lawyer&client=codex&model=gpt-smoke-model&effort=high&dry_run=1" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is True, f'launch dry-run with model/effort failed: {d}'
assert d.get('model') == 'gpt-smoke-model', d
assert d.get('effort') == 'high', d
assert 'codex --model gpt-smoke-model --effort high' in d.get('output',''), d
print('POST /api/launch model/effort dry-run OK')
" || { kill $srv_pid 2>/dev/null; echo "FAILED: launch model/effort dry-run failed"; exit 1; }

curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:$post_port/api/launch?workspace=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$workspace_root")&task=local-001&role=lawyer&client=codex" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is False, f'live launch in sandbox should fail: {d}'
assert 'sandbox' in d.get('error','').lower(), f'Missing sandbox guard error: {d}'
print('POST /api/launch live sandbox guard OK')
" || { kill $srv_pid 2>/dev/null; echo "FAILED: launch live sandbox guard did not reject"; exit 1; }

kill $srv_pid 2>/dev/null; wait $srv_pid 2>/dev/null || true

echo ">>> Verifying brain-dashboard auth token for write actions"
brain-task add "Smoke POST token" --role developer --prio P1 > /dev/null
token_task_id=$(grep "Smoke POST token" "$BRAIN_PATH/tasks/active.md" | grep -oE "t-[0-9-]+-smoke-post-token" | head -1)
[ -n "$token_task_id" ] || { echo "FAILED: could not create task for token POST test"; exit 1; }
token_port=$(pick_free_port)
BRAIN_DASHBOARD_AUTH_TOKEN="smoke-secret" brain-dashboard serve --port "$token_port" &
token_srv_pid=$!
wait_dashboard_port "$token_port"

curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:$token_port/api/tasks/$token_task_id?as=smoke-agent&action=take" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is False, f'POST without auth token should fail: {d}'
assert 'auth token' in d.get('error','').lower(), f'Missing auth token error: {d}'
print('POST auth missing token rejected OK')
" || { kill $token_srv_pid 2>/dev/null; echo "FAILED: POST without auth token not rejected"; exit 1; }

curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -H "X-Brain-Token: wrong" -X POST "http://127.0.0.1:$token_port/api/tasks/$token_task_id?as=smoke-agent&action=take" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is False, f'POST with wrong auth token should fail: {d}'
assert 'auth token' in d.get('error','').lower(), f'Missing auth token error: {d}'
print('POST auth wrong token rejected OK')
" || { kill $token_srv_pid 2>/dev/null; echo "FAILED: POST with wrong auth token not rejected"; exit 1; }

curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -H "X-Brain-Token: smoke-secret" -X POST "http://127.0.0.1:$token_port/api/tasks/$token_task_id?as=smoke-agent&action=take" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is True, f'POST with correct auth token failed: {d}'
print('POST auth correct token OK')
" || { kill $token_srv_pid 2>/dev/null; echo "FAILED: POST with correct auth token failed"; exit 1; }

curl -s --noproxy '*' "http://127.0.0.1:$token_port/api/status" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is False, f'GET without auth token should fail: {d}'
assert 'auth token' in d.get('error','').lower(), f'Missing auth token error: {d}'
print('GET auth missing token rejected OK')
" || { kill $token_srv_pid 2>/dev/null; echo "FAILED: GET without auth token not rejected"; exit 1; }

curl -s --noproxy '*' -H "X-Brain-Token: wrong" "http://127.0.0.1:$token_port/api/status" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is False, f'GET with wrong auth token should fail: {d}'
assert 'auth token' in d.get('error','').lower(), f'Missing auth token error: {d}'
print('GET auth wrong token rejected OK')
" || { kill $token_srv_pid 2>/dev/null; echo "FAILED: GET with wrong auth token not rejected"; exit 1; }

curl -s --noproxy '*' -H "X-Brain-Token: smoke-secret" "http://127.0.0.1:$token_port/api/status" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'tasks' in d, f'GET with correct auth header failed: {d}'
print('GET auth header token OK')
" || { kill $token_srv_pid 2>/dev/null; echo "FAILED: GET with correct auth header failed"; exit 1; }

curl -s --noproxy '*' "http://127.0.0.1:$token_port/api/status?token=smoke-secret" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'tasks' in d, f'GET with query token failed: {d}'
print('GET auth query token OK')
" || { kill $token_srv_pid 2>/dev/null; echo "FAILED: GET with query token failed"; exit 1; }

kill $token_srv_pid 2>/dev/null; wait $token_srv_pid 2>/dev/null || true

set +e
host_port=$(pick_free_port)
brain-dashboard serve --host 0.0.0.0 --port "$host_port" >/tmp/brain_dashboard_host.out 2>/tmp/brain_dashboard_host.err
host_rc=$?
set -e
[ "$host_rc" -ne 0 ] || {
  echo "FAILED: non-loopback dashboard started without auth token"
  exit 1
}
grep -qi "auth token" /tmp/brain_dashboard_host.err || {
  echo "FAILED: non-loopback refusal did not mention auth token"
  cat /tmp/brain_dashboard_host.err
  exit 1
}
