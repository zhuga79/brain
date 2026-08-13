#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying orchestrator auto-handoff from task output"

# Setup task and agent
task_id=$(brain-task add "Auto Handoff Test Task" --role developer --prio P1 | grep -oE "t-[0-9a-z-]+" | head -1)
agent="smoke-auto-handoff"

# 1. Test JSON output
cat <<EOF >/tmp/smoke-limit.json
{
  "type": "task-notification",
  "task_id": "$task_id",
  "agent_id": "$agent",
  "result": "You've hit your limit resets in 5 hours"
}
EOF

brain-handoff create --from-task-output /tmp/smoke-limit.json >/dev/null

# Verify JSON handoff artifact
grep -q "reason: limit-exhausted" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: json auto-handoff reason missing"; exit 1; }
grep -q "from_agent: $agent" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: json auto-handoff from_agent missing"; exit 1; }
grep -q "task: $task_id" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: json auto-handoff task missing"; exit 1; }
grep -q "orchestrator-handoff | $task_id | $agent | limit-exhausted" "$BRAIN_PATH/wiki/log.md" || { echo "FAILED: json auto-handoff log entry missing"; exit 1; }
echo "JSON auto-handoff OK"

# 2. Test Markdown output
cat <<EOF >/tmp/smoke-limit.md
Error from subagent:
task: $task_id
agent: $agent
result: rate_limit_error
EOF

brain-handoff create --from-task-output /tmp/smoke-limit.md >/dev/null

# Verify Markdown handoff artifact
grep -q "reason: rate-limit" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: md auto-handoff reason missing"; exit 1; }
grep -q "from_agent: $agent" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: md auto-handoff from_agent missing"; exit 1; }
grep -q "task: $task_id" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: md auto-handoff task missing"; exit 1; }
grep -q "orchestrator-handoff | $task_id | $agent | rate-limit" "$BRAIN_PATH/wiki/log.md" || { echo "FAILED: md auto-handoff log entry missing"; exit 1; }
echo "Markdown auto-handoff OK"

# 3. Test auto-from-clipboard with fake xclip
export PATH="/tmp/fake_bin:$PATH"
mkdir -p /tmp/fake_bin
cat <<EOF >/tmp/fake_bin/xclip
#!/bin/bash
cat /tmp/smoke-limit.md
EOF
chmod +x /tmp/fake_bin/xclip

brain-handoff auto-from-clipboard >/dev/null

# Verify clipboard handoff artifact
grep -q "reason: rate-limit" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: clipboard auto-handoff reason missing"; exit 1; }
grep -q "from_agent: $agent" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: clipboard auto-handoff from_agent missing"; exit 1; }
grep -q "task: $task_id" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: clipboard auto-handoff task missing"; exit 1; }
echo "Clipboard auto-handoff OK"

rm -rf /tmp/fake_bin /tmp/smoke-limit.json /tmp/smoke-limit.md
