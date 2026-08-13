#!/usr/bin/env bash
# case: handoff-journal
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying append-only handoff journal"

rm -rf "$BRAIN_PATH/handoff"
mkdir -p "$BRAIN_PATH/handoff"

TODAY=$(date -u +"%Y-%m-%d")

# Create 10 handoffs
for i in {1..10}; do
  brain-handoff create --reason manual --task "task-$i" >/dev/null 2>&1
done

JOURNAL="$BRAIN_PATH/handoff/journal-$TODAY.ndjson"
if [ ! -f "$JOURNAL" ]; then
  echo "FAILED: Journal file not created"
  exit 1
fi

LINE_COUNT=$(wc -l < "$JOURNAL")
if [ "$LINE_COUNT" -ne 10 ]; then
  echo "FAILED: Expected 10 lines in journal, got $LINE_COUNT"
  exit 1
fi

# Verify the latest record is task-10
LAST_LINE=$(tail -n 1 "$JOURNAL")
if ! echo "$LAST_LINE" | grep -q '"task": "task-10"'; then
  echo "FAILED: Last entry is not task-10"
  exit 1
fi

# Verify ORCHESTRATOR_HANDOFF.md matches the latest generated
LATEST_MD="$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md"
if [ ! -f "$LATEST_MD" ]; then
  echo "FAILED: ORCHESTRATOR_HANDOFF.md not found"
  exit 1
fi
if ! grep -q "task: task-10" "$LATEST_MD"; then
  echo "FAILED: ORCHESTRATOR_HANDOFF.md does not reflect task-10"
  exit 1
fi

# Verify rotation logic
OLD_DATE="2000-01-01"
OLD_JOURNAL="$BRAIN_PATH/handoff/journal-$OLD_DATE.ndjson"
touch "$OLD_JOURNAL"
touch "$BRAIN_PATH/handoff/journal-2099-01-01.ndjson"

# Trigger a write
brain-handoff create --reason manual --task "task-11" >/dev/null 2>&1

if [ -f "$OLD_JOURNAL" ]; then
  echo "FAILED: Old journal was not deleted during rotation"
  exit 1
fi

if [ ! -f "$BRAIN_PATH/handoff/journal-2099-01-01.ndjson" ]; then
  echo "FAILED: Future journal was deleted incorrectly"
  exit 1
fi

echo "handoff-journal OK"
