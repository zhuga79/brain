#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying folder-native workspace discovery"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

test -f "$PROJECT_ROOT/runtime/templates/workspace/BRAIN.md"
test -f "$PROJECT_ROOT/runtime/templates/workspace/TASKS.md"
test -f "$PROJECT_ROOT/runtime/templates/workspace/LOG.md"
grep -q "Agent Rules" "$PROJECT_ROOT/runtime/templates/workspace/BRAIN.md"
grep -q "Workspace Profile" "$PROJECT_ROOT/runtime/templates/workspace/BRAIN.md"
grep -q "Role Policy" "$PROJECT_ROOT/runtime/templates/workspace/BRAIN.md"
grep -q "Action Gates" "$PROJECT_ROOT/runtime/templates/workspace/BRAIN.md"
grep -q "Local Tasks" "$PROJECT_ROOT/runtime/templates/workspace/TASKS.md"
grep -q "Local Log" "$PROJECT_ROOT/runtime/templates/workspace/LOG.md"
command -v brain-workspace >/dev/null || { echo "FAILED: installed brain-workspace not found on PATH"; exit 1; }

TMP_ROOT="$BRAIN_FACTORY_TMP/workspaces"
mkdir -p "$TMP_ROOT/project-a/subdir" "$TMP_ROOT/project-b/.git/ignored"
cat > "$TMP_ROOT/project-a/BRAIN.md" <<'EOF'
# Workspace: A

## Role Policy

core:
- pm

available:
- lawyer

blocked:
- developer
EOF
cat > "$TMP_ROOT/project-a/TASKS.md" <<'EOF'
# Local Tasks

- [ ] [P1] local-001 - Draft local rules
      role: pm
      acceptance: BRAIN.md states write rules.

- [ ] [P1] local-blocked - Blocked developer task
      role: developer
      acceptance: Developer must not receive this task.
EOF
cat > "$TMP_ROOT/project-a/LOG.md" <<'EOF'
# Local Log

## 2026-05-27T18:31:29Z | test-agent | created

- Created workspace.
EOF
cat > "$TMP_ROOT/project-b/BRAIN.md" <<'EOF'
# Workspace: B
EOF
cat > "$TMP_ROOT/project-b/.git/ignored/BRAIN.md" <<'EOF'
# Ignored
EOF

discover_json=$(brain-workspace discover --root "$TMP_ROOT" --json)
echo "$discover_json" | grep -q '"title": "A"' || { echo "FAILED: discover missing Workspace A"; exit 1; }
echo "$discover_json" | grep -q '"open_tasks": 2' || { echo "FAILED: discover missing open task count"; exit 1; }
echo "$discover_json" | grep -q '"title": "B"' || { echo "FAILED: discover missing Workspace B"; exit 1; }
echo "$discover_json" | grep -q 'Ignored' && { echo "FAILED: discover included ignored workspace"; exit 1; }

summary=$(brain-workspace summary --root "$TMP_ROOT")
echo "$summary" | grep -q "A" || { echo "FAILED: summary missing Workspace A"; exit 1; }
echo "$summary" | grep -q "open=2" || { echo "FAILED: summary missing open count"; exit 1; }

nearest=$(brain-workspace nearest "$TMP_ROOT/project-a/subdir")
[ "$nearest" = "$TMP_ROOT/project-a" ] || { echo "FAILED: nearest returned $nearest"; exit 1; }

next_task=$(brain-workspace next --workspace "$TMP_ROOT/project-a" --role pm)
echo "$next_task" | grep -q "local-001" || { echo "FAILED: next did not return local-001"; exit 1; }

if brain-workspace next --workspace "$TMP_ROOT/project-a" --role developer >/tmp/brain_workspace_blocked_next.out 2>&1; then
  echo "FAILED: blocked developer role received a local task"
  exit 1
fi
if brain-workspace take --workspace "$TMP_ROOT/project-a" local-blocked --as test-agent >/tmp/brain_workspace_blocked_take.out 2>&1; then
  echo "FAILED: blocked developer role task was taken"
  exit 1
fi
grep -q "not allowed" /tmp/brain_workspace_blocked_take.out || {
  echo "FAILED: blocked role error did not explain role policy"
  cat /tmp/brain_workspace_blocked_take.out
  exit 1
}

cat >> "$TMP_ROOT/project-a/TASKS.md" <<'EOF'

- [ ] [P1] local-002 - Review claim drafts
      role: lawyer
      acceptance: legal review is complete.
EOF
mkdir -p "$BRAIN_PATH/roles"
cat > "$BRAIN_PATH/roles/lawyer.md" <<'EOF'
# Lawyer
EOF
run_prompt=$(brain-run --workspace "$TMP_ROOT/project-a" --role lawyer --task local-002 --client codex)
echo "$run_prompt" | grep -q "# === WORKSPACE: $TMP_ROOT/project-a ===" || {
  echo "FAILED: brain-run did not include workspace context"
  exit 1
}
echo "$run_prompt" | grep -q -- "- \\[ \\] \\[P1\\] local-002 - Review claim drafts" || {
  echo "FAILED: brain-run did not include local workspace task"
  exit 1
}
echo "$run_prompt" | grep -q "brain-workspace take --workspace" || {
  echo "FAILED: brain-run workspace prompt did not instruct local take"
  exit 1
}
echo "$run_prompt" | grep -q "Action Gates" || {
  echo "FAILED: brain-run workspace prompt did not include action gates"
  exit 1
}
brain-orchestrator --brain "$BRAIN_PATH" console \
  --workspace "$TMP_ROOT/project-a" \
  --role lawyer \
  --task local-002 \
  --agent workspace-smoke \
  --primary 'cat {prompt}' \
  --no-visible \
  --dry-run > /tmp/brain_workspace_orchestrator_prompt.out
grep -q "operator console plan" /tmp/brain_workspace_orchestrator_prompt.out || {
  echo "FAILED: brain-orchestrator workspace dry-run missing plan"
  cat /tmp/brain_workspace_orchestrator_prompt.out
  exit 1
}
grep -q "workspace  : $TMP_ROOT/project-a" /tmp/brain_workspace_orchestrator_prompt.out || {
  echo "FAILED: brain-orchestrator workspace dry-run missing resolved workspace"
  cat /tmp/brain_workspace_orchestrator_prompt.out
  exit 1
}

brain-workspace take --workspace "$TMP_ROOT/project-a" local-001 --as test-agent >/dev/null
grep -q -- "- \\[~\\] \\[P1\\] local-001 - Draft local rules" "$TMP_ROOT/project-a/TASKS.md" || {
  echo "FAILED: take did not mark local-001 in progress"
  exit 1
}

brain-workspace complete --workspace "$TMP_ROOT/project-a" local-001 --as test-agent --model "openai-gpt-5.4" --summary "rules drafted" >/dev/null
grep -q -- "- \\[x\\] \\[P1\\] local-001 - Draft local rules" "$TMP_ROOT/project-a/TASKS.md" || {
  echo "FAILED: complete did not mark local-001 done"
  exit 1
}
grep -q "rules drafted" "$TMP_ROOT/project-a/LOG.md" || {
  echo "FAILED: complete did not append local log"
  exit 1
}

brain-workspace init-template --out "$TMP_ROOT/project-c" >/dev/null
test -f "$TMP_ROOT/project-c/BRAIN.md"
test -f "$TMP_ROOT/project-c/TASKS.md"
test -f "$TMP_ROOT/project-c/LOG.md"

echo "workspace discovery OK"
