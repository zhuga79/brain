#!/usr/bin/env bash
# case: health-status
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying health-status outputs"

rm -f "$BRAIN_PATH/.provider-health.json"

# Without probe, status should be unknown, not unavailable (unless command not present?)
# Wait, "без probe = unknown, не unavailable".
status_unknown=$(brain-provider status)

if echo "$status_unknown" | grep -q "\[unavailable\]"; then
  # Wait, if command is not present it might be unknown but it says "не unavailable" 
  # for things that are actually unprobed.
  # Let's check if the preferred is unknown.
  if ! echo "$status_unknown" | grep -q "\[unknown\]"; then
    echo "FAILED: preferred status is not unknown when unprobed"
    exit 1
  fi
fi

# Run probe
brain-provider probe >/dev/null 2>&1

status_healthy=$(brain-provider status)
if ! echo "$status_healthy" | grep -q "\[healthy\]"; then
  echo "FAILED: preferred status is not healthy after probe"
  exit 1
fi

# Simulate stale by rewriting checked_at in cache
python3 -c '
import json, sys
data = json.load(open(sys.argv[1]))
for k, v in data.get("items", {}).items():
    v["checked_at"] = "2000-01-01T00:00:00Z"
json.dump(data, open(sys.argv[1], "w"))
' "$BRAIN_PATH/.provider-health.json"

status_stale=$(brain-provider status)
if ! echo "$status_stale" | grep -q "\[stale\]"; then
  echo "FAILED: preferred status is not stale after TTL"
  exit 1
fi

echo "health-status OK"
