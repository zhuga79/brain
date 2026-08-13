#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-orchestrator console"

task_id=$(brain-task add "Operator Console Test Task" --role developer --prio P1 | grep -oE "t-[0-9a-z-]+" | head -1)
agent="smoke-console"

brain-orchestrator console \
  --task "$task_id" \
  --role developer \
  --agent "$agent" \
  --primary "bash -lc 'test -f {prompt}; grep -q \"# === TASK:\" {prompt}; echo console-primary-ok'" \
  --fallback "bash -lc 'echo console-fallback-ok'" \
  --no-visible \
  --dry-run \
  >/tmp/brain_orchestrator_console_dryrun.out

grep -q "operator console plan" /tmp/brain_orchestrator_console_dryrun.out || {
  echo "FAILED: console dry-run missing plan"
  cat /tmp/brain_orchestrator_console_dryrun.out
  exit 1
}
grep -q "$task_id" /tmp/brain_orchestrator_console_dryrun.out || {
  echo "FAILED: console dry-run missing task id"
  cat /tmp/brain_orchestrator_console_dryrun.out
  exit 1
}
grep -q "$BRAIN_PATH/.brain/orchestrator/prompts/" /tmp/brain_orchestrator_console_dryrun.out || {
  echo "FAILED: console dry-run missing prompt path"
  cat /tmp/brain_orchestrator_console_dryrun.out
  exit 1
}
grep -q "$BRAIN_PATH/.brain/orchestrator/logs/" /tmp/brain_orchestrator_console_dryrun.out || {
  echo "FAILED: console dry-run missing log path"
  cat /tmp/brain_orchestrator_console_dryrun.out
  exit 1
}

brain-orchestrator console \
  --task "$task_id" \
  --role developer \
  --agent "$agent" \
  --primary "codex" \
  --model "gpt-smoke-model" \
  --effort "high" \
  --no-visible \
  --dry-run \
  >/tmp/brain_orchestrator_console_override_dryrun.out

grep -q "codex --model gpt-smoke-model --effort high" /tmp/brain_orchestrator_console_override_dryrun.out || {
  echo "FAILED: console dry-run did not apply model/effort override"
  cat /tmp/brain_orchestrator_console_override_dryrun.out
  exit 1
}

brain-orchestrator run \
  --task "$task_id" \
  --agent "$agent" \
  --to-role developer \
  --model "gpt-smoke-model" \
  --effort "high" \
  --dry-run \
  -- codex \
  >/tmp/brain_orchestrator_run_override_dryrun.out

grep -q "codex --model gpt-smoke-model --effort high" /tmp/brain_orchestrator_run_override_dryrun.out || {
  echo "FAILED: run dry-run did not apply model/effort override"
  cat /tmp/brain_orchestrator_run_override_dryrun.out
  exit 1
}

workspace_root="$(mktemp -d)/operator-workspace"
mkdir -p "$workspace_root/subdir"
cat > "$workspace_root/BRAIN.md" <<'EOF'
# Workspace: Operator Smoke
EOF

brain-orchestrator console \
  --task "$task_id" \
  --role developer \
  --agent "$agent" \
  --workspace "$workspace_root/subdir" \
  --primary "bash -lc 'test -f {prompt}; grep -q \"# === TASK:\" {prompt}; echo console-primary-ok'" \
  --fallback "bash -lc 'echo console-fallback-ok'" \
  --no-visible \
  --dry-run \
  >/tmp/brain_orchestrator_console_workspace_dryrun.out

grep -q "workspace  : $workspace_root" /tmp/brain_orchestrator_console_workspace_dryrun.out || {
  echo "FAILED: workspace dry-run missing resolved workspace"
  cat /tmp/brain_orchestrator_console_workspace_dryrun.out
  exit 1
}
grep -q "BRAIN.md   : $workspace_root/BRAIN.md" /tmp/brain_orchestrator_console_workspace_dryrun.out || {
  echo "FAILED: workspace dry-run missing BRAIN.md path"
  cat /tmp/brain_orchestrator_console_workspace_dryrun.out
  exit 1
}
prompt_file="$BRAIN_PATH/.brain/orchestrator/prompts/$task_id.$agent.prompt.md"
log_file="$BRAIN_PATH/.brain/orchestrator/logs/$task_id.$agent.log"
[ ! -f "$prompt_file" ] || {
  echo "FAILED: console dry-run created prompt file"
  exit 1
}
[ ! -f "$log_file" ] || {
  echo "FAILED: console dry-run created log file"
  exit 1
}

if [ "${CODEX_SANDBOX_NETWORK_DISABLED:-}" = "1" ]; then
  if brain-orchestrator console \
    --task "$task_id" \
    --role developer \
    --agent "$agent" \
    --primary "bash -lc 'echo should-not-run'" \
    --no-visible \
    >/tmp/brain_orchestrator_console_sandbox.out 2>/tmp/brain_orchestrator_console_sandbox.err; then
    echo "FAILED: console live launch was allowed inside sandbox"
    exit 1
  fi
  grep -q "Refusing brain-orchestrator console inside sandbox" /tmp/brain_orchestrator_console_sandbox.err || {
    echo "FAILED: sandbox refusal did not explain console launch guard"
    cat /tmp/brain_orchestrator_console_sandbox.err
    exit 1
  }
  echo "brain-orchestrator console OK (sandbox live launch refused)"
  exit 0
fi

brain-orchestrator console \
  --task "$task_id" \
  --role developer \
  --agent "$agent" \
  --primary "bash -lc 'test -f {prompt}; grep -q \"# === TASK:\" {prompt}; echo console-primary-ok'" \
  --no-visible \
  >/tmp/brain_orchestrator_console.out 2>/tmp/brain_orchestrator_console.err

grep -q "console-primary-ok" /tmp/brain_orchestrator_console.out || {
  echo "FAILED: console primary command did not run"
  cat /tmp/brain_orchestrator_console.out
  cat /tmp/brain_orchestrator_console.err
  exit 1
}

prompt_file="$BRAIN_PATH/.brain/orchestrator/prompts/$task_id.$agent.prompt.md"
[ -f "$prompt_file" ] || {
  echo "FAILED: console prompt file missing: $prompt_file"
  exit 1
}
grep -q "$task_id" "$prompt_file" || {
  echo "FAILED: prompt file missing task id"
  exit 1
}
[ -f "$log_file" ] || {
  echo "FAILED: console log file missing: $log_file"
  exit 1
}
grep -q "console-primary-ok" "$log_file" || {
  echo "FAILED: console log file missing primary output"
  cat "$log_file"
  exit 1
}
grep -q "$log_file" "$BRAIN_PATH/.brain/orchestrator/latest.json" || {
  echo "FAILED: latest operator manifest missing log path"
  cat "$BRAIN_PATH/.brain/orchestrator/latest.json"
  exit 1
}

echo "brain-orchestrator console OK"
