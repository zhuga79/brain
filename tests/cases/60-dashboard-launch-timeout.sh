#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying dashboard launch endpoints time out instead of hanging"

brain_factory

# Shim brain-orchestrator with a script that hangs longer than the timeout.
shim_dir="$(mktemp -d /tmp/brain-launch-timeout.XXXXXX)"
cat > "$shim_dir/brain-orchestrator" <<'SH'
#!/usr/bin/env bash
sleep 30
SH
chmod +x "$shim_dir/brain-orchestrator"
export PATH="$shim_dir:$PROJECT_ROOT/runtime/bin:$PATH"
export BRAIN_LAUNCH_TIMEOUT=1

mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki" "$BRAIN_PATH/roles" "$BRAIN_PATH/.brain/launch-queue"
printf '# Active Tasks\n' > "$BRAIN_PATH/tasks/active.md"
printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"
printf '# Developer\n' > "$BRAIN_PATH/roles/developer.md"
cat > "$BRAIN_PATH/.brain/launch-queue/proposals.json" <<'JSON'
{
  "ok": true,
  "proposals": [
    {"id": "qp-hang", "status": "pending", "task": "t-2026-05-29-hang", "title": "Hang", "role": "developer", "client": "codex", "workspace": ""}
  ]
}
JSON

# No sandbox guard here: we want the launch to actually run the (hanging) shim.
# The surrounding Codex session may set CODEX_SANDBOX_NETWORK_DISABLED=1; clear
# it for this child so the dashboard launch guard does not mask timeout behavior.
env -u CODEX_SANDBOX_NETWORK_DISABLED brain-dashboard serve --port 19990 &
srv_pid=$!
trap 'kill $srv_pid 2>/dev/null || true; rm -rf "$shim_dir"' EXIT
sleep 1

start=$(date +%s)
http_code=$(curl -s --noproxy '*' -o /tmp/brain-timeout-body.json -w '%{http_code}' \
  -H "X-Brain-Confirm: 1" -X POST \
  "http://127.0.0.1:19990/api/queue-proposals/qp-hang/launch?dry_run=0")
elapsed=$(( $(date +%s) - start ))

[ "$http_code" = "504" ] || { echo "FAILED: expected 504, got $http_code; body=$(cat /tmp/brain-timeout-body.json)"; exit 1; }
[ "$elapsed" -lt 15 ] || { echo "FAILED: request took ${elapsed}s, timeout did not fire"; exit 1; }
python3 -c "import json;d=json.load(open('/tmp/brain-timeout-body.json'));assert d['ok'] is False and 'timed out' in d['error'], d" \
  || { echo "FAILED: timeout body malformed"; exit 1; }
python3 - "$BRAIN_PATH/.brain/launch-queue/proposals.json" <<'PY' \
  || { echo "FAILED: timeout did not leave auditable error state"; exit 1; }
import json, sys
data = json.load(open(sys.argv[1]))
proposal = data["proposals"][0]
assert proposal["status"] == "error", proposal
assert "timed out" in proposal.get("error", ""), proposal
assert proposal.get("launching_at"), proposal
assert proposal.get("error_at"), proposal
PY
echo "queue-proposal launch returns 504 on timeout (${elapsed}s) OK"

echo ">>> dashboard launch timeout checks passed"
