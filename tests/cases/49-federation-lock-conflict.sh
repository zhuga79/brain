#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-federation federated lock conflict detection"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

# 1. Setup repo and a locked task
mkdir -p "$BRAIN_PATH/.locks/t-locked"
touch "$BRAIN_PATH/.locks/t-locked/lock.json"
mkdir -p "$BRAIN_PATH/tasks"
cat << 'EOF' > "$BRAIN_PATH/tasks/active.md"
# Active tasks
- [ ] [P1] t-locked — Locked Task
      role: developer
EOF

# Initialize git repo for preflight
cd "$BRAIN_PATH"
git config --global init.defaultBranch master
git init >/dev/null
git config user.email "smoke@test.com"
git config user.name "Smoke Test"
echo ".locks/" > .gitignore
echo "wiki/proposals/" >> .gitignore
echo "learning/lessons/" >> .gitignore
git add tasks/active.md .gitignore
git commit -m "Initial" >/dev/null

# 2. Simulate a remote change to the locked task
# In git_paths logic, this means the file is changed compared to HEAD
echo "changed" >> tasks/active.md

# 3. Run preflight
python3 "$PROJECT_ROOT/runtime/bin/brain-federation" preflight --json > preflight.json || true

# 4. Verify finding
grep -q "federated-lock-warning" preflight.json || { echo "FAILED: preflight did not detect lock conflict"; cat preflight.json; exit 1; }
grep -q "task t-locked is locked locally but task files changed in remote" preflight.json || { echo "FAILED: wrong warning message"; exit 1; }

echo "brain-federation federated lock conflict detection OK"
