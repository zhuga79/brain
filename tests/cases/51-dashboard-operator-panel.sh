#!/usr/bin/env bash
# case: dashboard-operator-panel
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-dashboard Operator Console panel"

task_id=$(brain-task add "Dashboard operator panel test" --role developer --prio P1 | grep -oE "t-[0-9a-z-]+" | head -1)
agent="operator-panel-smoke"
prompt_file="$BRAIN_PATH/.brain/orchestrator/prompts/$task_id.$agent.prompt.md"
log_file="$BRAIN_PATH/.brain/orchestrator/logs/$task_id.$agent.log"
mkdir -p "$(dirname "$prompt_file")" "$(dirname "$log_file")" "$BRAIN_PATH/.brain/orchestrator"
printf '# prompt for %s\n' "$task_id" > "$prompt_file"
printf 'operator-log-output\n' > "$log_file"
cat > "$BRAIN_PATH/.brain/orchestrator/latest.json" <<EOF
{
  "updated": "2026-05-16T07:30:00Z",
  "task": "$task_id",
  "role": "developer",
  "agent": "$agent",
  "prompt": "$prompt_file",
  "log": "$log_file"
}
EOF

brain-handoff create --reason limit-exhausted --from "$agent" --to-role developer --task "$task_id" >/dev/null

mkdir -p "$BRAIN_PATH/.brain"
cat > "$BRAIN_PATH/.brain/token-metrics.jsonl" <<EOF
{"ts":"2026-05-16T07:30:01Z","kind":"compact","provider":"codex","role":"developer","session":"smoke","raw_tokens_est":1000,"compact_tokens_est":250,"savings_percent":75,"raw_artifact":"raw.md"}
EOF

brain-dashboard export --out /tmp/dashboard_operator_panel.html

grep -q 'id="operator-console"' /tmp/dashboard_operator_panel.html || {
  echo "FAILED: Operator Console section missing"
  exit 1
}
grep -q "$task_id" /tmp/dashboard_operator_panel.html || {
  echo "FAILED: operator panel missing task id"
  exit 1
}
grep -q "$agent" /tmp/dashboard_operator_panel.html || {
  echo "FAILED: operator panel missing agent"
  exit 1
}
grep -q "$prompt_file" /tmp/dashboard_operator_panel.html || {
  echo "FAILED: operator panel missing prompt path"
  exit 1
}
grep -q "$log_file" /tmp/dashboard_operator_panel.html || {
  echo "FAILED: operator panel missing log path"
  exit 1
}
grep -q "limit-exhausted" /tmp/dashboard_operator_panel.html || {
  echo "FAILED: operator panel missing handoff reason"
  exit 1
}
grep -q "compacted command" /tmp/dashboard_operator_panel.html || {
  echo "FAILED: operator panel missing token economy summary"
  exit 1
}

echo "dashboard-operator-panel OK"
