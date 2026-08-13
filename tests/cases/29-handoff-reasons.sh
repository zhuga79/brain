#!/usr/bin/env bash
# case: handoff-reasons
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying handoff reasons validation"

# Test valid reasons
for reason in limit-near limit-exhausted rate-limit context-bleed manual done; do
  brain-handoff create --reason "$reason" --out "/tmp/handoff_test_${reason}.md" >/dev/null 2>&1
  if [ ! -f "/tmp/handoff_test_${reason}.md" ]; then
    echo "FAILED: valid reason $reason did not create file"
    exit 1
  fi
  rm -f "/tmp/handoff_test_${reason}.md"
done

# Test invalid reason
set +e
output=$(brain-handoff create --reason "invalid-reason" --out /tmp/handoff_test_invalid.md 2>&1)
rc=$?
set -e

if [ "$rc" -eq 0 ]; then
  echo "FAILED: invalid reason did not fail"
  exit 1
fi

if ! echo "$output" | grep -q "error: unknown handoff reason 'invalid-reason'"; then
  echo "FAILED: invalid reason output incorrect: $output"
  exit 1
fi

echo "handoff-reasons OK"
