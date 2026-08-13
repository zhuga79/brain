#!/usr/bin/env bash
# case: handoff-cli
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-handoff CLI commands (list, show, tail)"

rm -rf "$BRAIN_PATH/handoff"
mkdir -p "$BRAIN_PATH/handoff"

TODAY=$(date -u +"%Y-%m-%d")

# Generate some handoffs for testing
brain-handoff create --reason limit-near --task "task-A" --from "agent-X" >/dev/null 2>&1
sleep 1
brain-handoff create --reason manual --task "task-B" --from "agent-Y" >/dev/null 2>&1
sleep 1
brain-handoff create --reason rate-limit --task "task-A" --from "agent-Y" >/dev/null 2>&1
sleep 1
brain-handoff create --reason manual --task "task-C" --from "agent-Z" >/dev/null 2>&1
sleep 1
brain-handoff create --reason done --task "task-B" --from "agent-X" >/dev/null 2>&1

# 1. Test 'list' command
list_output=$(brain-handoff list)
line_count=$(echo "$list_output" | wc -l)
if [ "$line_count" -ne 5 ]; then
  echo "FAILED: Expected 5 lines in list output, got $line_count"
  exit 1
fi

list_task_A=$(brain-handoff list --task "task-A")
line_count_A=$(echo "$list_task_A" | wc -l)
if [ "$line_count_A" -ne 2 ]; then
  echo "FAILED: Expected 2 lines for task-A, got $line_count_A"
  exit 1
fi

list_agent_Y=$(brain-handoff list --agent "agent-Y")
line_count_Y=$(echo "$list_agent_Y" | wc -l)
if [ "$line_count_Y" -ne 2 ]; then
  echo "FAILED: Expected 2 lines for agent-Y, got $line_count_Y"
  exit 1
fi

list_reason_manual=$(brain-handoff list --reason manual)
line_count_manual=$(echo "$list_reason_manual" | wc -l)
if [ "$line_count_manual" -ne 2 ]; then
  echo "FAILED: Expected 2 lines for reason manual, got $line_count_manual"
  exit 1
fi

# 2. Test 'tail' command
tail_output=$(brain-handoff tail -n 3)
line_count_tail=$(echo "$tail_output" | wc -l)
if [ "$line_count_tail" -ne 3 ]; then
  echo "FAILED: Expected 3 lines from tail, got $line_count_tail"
  exit 1
fi

# tail idempotency check
tail_1=$(brain-handoff tail -n 5)
tail_2=$(brain-handoff tail -n 5)
if [ "$tail_1" != "$tail_2" ]; then
  echo "FAILED: tail -n 5 is not idempotent"
  exit 1
fi

# 3. Test 'show' command
# Get the ID of the last handoff
last_id=$(echo "$list_output" | tail -n 1 | awk '{print $1}')
show_output=$(brain-handoff show "$last_id")
if ! echo "$show_output" | grep -q "task: task-B"; then
  echo "FAILED: show output does not contain expected task for ID $last_id"
  exit 1
fi

if ! echo "$show_output" | grep -q "reason: done"; then
  echo "FAILED: show output does not contain expected reason for ID $last_id"
  exit 1
fi

echo "handoff-cli OK"
