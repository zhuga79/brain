#!/usr/bin/env bash
# case: runner-case-timeout — a hung case must not stall the whole suite.
# tests/run.sh runs each case under `timeout`; on expiry the case is FAILED
# with a "timeout Ns" line, the runner moves on, the case's backgrounded
# processes are torn down with its process group, and the run lock is freed.
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying per-case timeout in tests/run.sh"

work="$(mktemp -d)"
ALL_TMPDIRS+=("$work")
stub_cases="$work/cases"
mkdir -p "$stub_cases"
marker="$work/orphan.pid"
nested_lock="$work/nested-run.lock"
out="$work/nested.out"

# A case that hangs well past the test ceiling and leaves a background child.
cat > "$stub_cases/10-hang.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
sleep 300 &
echo \$! > "$marker"
echo "hang stub: sleeping past the ceiling"
sleep 300
EOF

# A case after it — proves the runner kept going.
cat > "$stub_cases/20-after.sh" <<'EOF'
#!/usr/bin/env bash
echo "ran after the hang"
EOF
chmod +x "$stub_cases"/*.sh

set +e
BRAIN_SMOKE_CASES_DIR="$stub_cases" \
BRAIN_SMOKE_SKIP_BOOTSTRAP=1 \
BRAIN_SMOKE_CASE_TIMEOUT=2 \
BRAIN_SMOKE_CASE_KILL_GRACE=1 \
BRAIN_SMOKE_RUN_LOCK="$nested_lock" \
  bash "$PROJECT_ROOT/tests/run.sh" > "$out" 2>&1
nested_rc=$?
set -e

[ "$nested_rc" -ne 0 ] || { echo "FAILED: nested runner exited 0 despite a timed-out case"; cat "$out"; exit 1; }

grep -Eq '\[case: 10-hang\] FAILED \(timeout 2s\)' "$out" \
  || { echo "FAILED: hung case not reported as a timeout"; cat "$out"; exit 1; }
grep -Eq '\[case: 20-after\] PASSED' "$out" \
  || { echo "FAILED: runner did not continue to the next case after a timeout"; cat "$out"; exit 1; }
grep -Eq 'Results: 1 passed, 1 failed' "$out" \
  || { echo "FAILED: summary did not count the timeout as one failure"; cat "$out"; exit 1; }

# The hung case's background child must not outlive its process group.
orphan="$(cat "$marker" 2>/dev/null || true)"
[ -n "$orphan" ] || { echo "FAILED: stub never recorded its background pid"; cat "$out"; exit 1; }
for _ in 1 2 3 4 5 6 7 8 9 10; do
  kill -0 "$orphan" 2>/dev/null || break
  sleep 0.5
done
if kill -0 "$orphan" 2>/dev/null; then
  kill -KILL "$orphan" 2>/dev/null || true
  echo "FAILED: background child $orphan of the timed-out case was orphaned"
  exit 1
fi

# The run lock must be free once the nested runner exits.
if command -v flock >/dev/null 2>&1; then
  flock -n "$nested_lock" true \
    || { echo "FAILED: run lock still held after the nested runner exited"; exit 1; }
fi

echo "runner-case-timeout OK"
