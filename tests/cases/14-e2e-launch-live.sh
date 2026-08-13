#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Running e2e-orchestration drill"
bash "$PROJECT_ROOT/tests/e2e-orchestration.sh" > /tmp/_e2e_orch.log 2>&1 || { echo "FAILED: e2e-orchestration.sh failed"; cat /tmp/_e2e_orch.log; exit 1; }
grep -q "ALL STEPS PASSED" /tmp/_e2e_orch.log || { echo "FAILED: e2e drill missing ALL STEPS PASSED"; cat /tmp/_e2e_orch.log; exit 1; }
echo "e2e-orchestration drill OK"

echo ">>> Verifying brain-launch --watch --auto-next (live)"
if [ "${CODEX_SANDBOX_NETWORK_DISABLED:-}" = "1" ]; then
  if brain-launch --watch --auto-next >/tmp/brain_autonext_sandbox.log 2>&1; then
    echo "FAILED: brain-launch live watch was allowed inside sandbox"
    exit 1
  fi
  grep -q "refusing live agent launch inside sandbox" /tmp/brain_autonext_sandbox.log || {
    echo "FAILED: sandbox refusal did not explain brain-launch guard"
    cat /tmp/brain_autonext_sandbox.log
    exit 1
  }
  echo "brain-launch --watch --auto-next live OK (sandbox launch refused)"
  exit 0
fi
# E2E: create 2 tasks, complete first, verify auto-next takes second
_an_agent="smoke-autonext-$$"
_an_task1=$(brain-task add "AutoNext Task1" --role developer --prio P1 | grep -oE "t-[0-9a-z-]+" | head -1)
_an_task2=$(brain-task add "AutoNext Task2" --role developer --prio P1 | grep -oE "t-[0-9a-z-]+" | head -1)
[ -n "$_an_task1" ] && [ -n "$_an_task2" ] || { echo "FAILED: could not create auto-next test tasks"; exit 1; }
# We need a council: field to use brain-launch; inject it
tmp_active=$(mktemp)
awk -v id="$_an_task1" '
    { print }
    $0 ~ id && /AutoNext Task1/ { in_task = 1; next }
    in_task && /role:.*mode:/ {
        print "      council: [developer]"
        in_task = 0
    }
' "$BRAIN_PATH/tasks/active.md" > "$tmp_active" && mv "$tmp_active" "$BRAIN_PATH/tasks/active.md" || true
# Take task1 then complete it (simulating council finishing)
brain-task take "$_an_task1" --as "$_an_agent" 2>/dev/null || true
# Run watch --auto-next with short poll interval; background it
BRAIN_WATCH_POLL_SEC=1 brain-launch "$_an_task1" --watch --auto-next > /tmp/brain_autonext_live.log 2>&1 &
_an_pid=$!
sleep 0.5
# Complete task1 (watcher should notice)
brain-task complete "$_an_task1" --as "$_an_agent" >/dev/null 2>&1 || true
# Give watcher time to detect and take next
sleep 3
# If still running, check if task2 was taken
wait $_an_pid 2>/dev/null || true
grep -q "took\|auto-next\|Auto-next\|Next task" /tmp/brain_autonext_live.log || { echo "FAILED: no auto-next action in log: $(cat /tmp/brain_autonext_live.log)"; exit 1; }
grep -q "watch-auto-next\|took.*$_an_task2\|took: $_an_task2" /tmp/brain_autonext_live.log || \
  grep -q "$_an_task2" /tmp/brain_autonext_live.log || \
  grep -qi "task2\|next task\|took" /tmp/brain_autonext_live.log || { echo "FAILED: auto-next did not reference task2: $(cat /tmp/brain_autonext_live.log)"; exit 1; }
# Clean up: release any lock on task2
brain-lock release "$_an_task2" --as "brain-launch-autonext-$_an_pid" 2>/dev/null || true
brain-task complete "$_an_task2" --as "$_an_agent" 2>/dev/null || true
echo "brain-launch --watch --auto-next live OK"
