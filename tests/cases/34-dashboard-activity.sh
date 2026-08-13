#!/usr/bin/env bash
# case: dashboard-activity
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-dashboard Activity block"

# Reset brain to empty state
rm -rf "$BRAIN_PATH/handoff" "$BRAIN_PATH/.locks"
mkdir -p "$BRAIN_PATH/handoff"
printf "# Active tasks\n\n## P1\n" > "$BRAIN_PATH/tasks/active.md"

# 1. Test empty state
brain-dashboard export --out /tmp/dashboard_empty.html
if ! grep -qi "No active work" /tmp/dashboard_empty.html; then
  echo "FAILED: Activity block did not show 'No active work' when idle"
  cat /tmp/dashboard_empty.html
  exit 1
fi

# 2. Test in-progress state
tid=$(brain-task add "Smoke activity test" --role developer --prio P1 | grep -oE "t-[0-9a-z-]+")
brain-task take "$tid" --as "gemini-3-flash-test-agent"

brain-dashboard export --out /tmp/dashboard_active.html

if grep -qi "No active work" /tmp/dashboard_active.html; then
  echo "FAILED: Activity block showed 'No active work' when a task is in progress"
  cat /tmp/dashboard_active.html
  exit 1
fi

if ! grep -q "$tid" /tmp/dashboard_active.html; then
  echo "FAILED: Activity block missing task ID $tid"
  exit 1
fi

if ! grep -q "gemini-3-flash-test-agent" /tmp/dashboard_active.html; then
  echo "FAILED: Activity block missing agent ID"
  exit 1
fi

if ! grep -q "gemini" /tmp/dashboard_active.html; then
  echo "FAILED: Activity block missing provider (gemini)"
  exit 1
fi

echo "dashboard-activity OK"
