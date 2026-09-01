#!/usr/bin/env bash
# Test: signature-based auto-refresh (reload only when state actually changes).
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying dashboard signature-based auto-refresh"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki"
cat > "$BRAIN_PATH/tasks/active.md" <<'T1'
# Active Tasks

- [ ] [P1] t-2026-05-30-x — Задача
      role: developer   mode: solo
      acceptance: ok
T1
printf '# Done\n' > "$BRAIN_PATH/tasks/done.md"
printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"

sig() {
  brain-dashboard export > /dev/null
  grep -oE '<meta name="state-sig" content="[a-f0-9]+">' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" | grep -oE '[a-f0-9]{8,}'
}
s1="$(sig)"
[ -n "$s1" ] || { echo "FAILED: state-sig meta missing"; exit 1; }
echo "OK: state-sig meta present ($s1)"

# change task state -> signature must change
sed -i 's/- \[ \] \[P1\] t-2026-05-30-x/- [~] [P1] t-2026-05-30-x/' "$BRAIN_PATH/tasks/active.md"
s2="$(sig)"
[ "$s1" != "$s2" ] || { echo "FAILED: signature did not change on state change"; exit 1; }
echo "OK: signature changes on real state change ($s1 -> $s2)"

# same content -> same signature (no spurious reload)
s3="$(sig)"
[ "$s2" = "$s3" ] || { echo "FAILED: signature unstable across identical renders"; exit 1; }
echo "OK: signature stable when nothing changes"

# JS wiring lives in the live (serve) page, not static export.
port=$(pick_free_port)
brain-dashboard serve --port "$port" &
srv_pid=$!
trap 'kill $srv_pid 2>/dev/null || true' EXIT
wait_dashboard_port "$port"
page="$(curl -s --noproxy '*' "http://127.0.0.1:$port/")"
grep -q "nextSig" <<< "$page" || { echo "FAILED: auto-refresh JS missing on live page"; exit 1; }
grep -q "_busy" <<< "$page" || { echo "FAILED: busy guard missing"; exit 1; }
grep -q 'name="state-sig"' <<< "$page" || { echo "FAILED: state-sig meta missing on live page"; exit 1; }
echo "OK: auto-refresh JS wired (signature + busy guard)"

# /api/status exposes the signature for the poll to compare
curl -s --noproxy '*' "http://127.0.0.1:$port/api/status" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('signature'), 'no signature in /api/status'; print('OK: /api/status exposes signature', d['signature'])" || { echo "FAILED: /api/status signature missing"; exit 1; }

echo "dashboard auto-refresh test PASSED"
