#!/usr/bin/env bash
# case: dashboard-handoffs
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-dashboard Recent Handoffs block"

rm -rf "$BRAIN_PATH/handoff"
mkdir -p "$BRAIN_PATH/handoff"

# Generate handoffs for each reason
reasons=(limit-near limit-exhausted rate-limit context-bleed manual fallback done)

for reason in "${reasons[@]}"; do
  brain-handoff create --reason "$reason" --task "task-$reason" >/dev/null 2>&1
  sleep 0.1 # Ensure different timestamps
done

brain-dashboard export --out /tmp/dashboard_handoffs.html

# Check if each reason badge is present
for reason in "${reasons[@]}"; do
  if ! grep -q ">$reason</span>" /tmp/dashboard_handoffs.html; then
    echo "FAILED: Badge for reason $reason not found in dashboard"
    exit 1
  fi
done

# Check if journal section header is present
if ! grep -q "Recent Handoffs (Journal)" /tmp/dashboard_handoffs.html; then
  echo "FAILED: Journal section header not found"
  exit 1
fi

echo "dashboard-handoffs OK"
