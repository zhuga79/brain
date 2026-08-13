#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-validate-cycle"

# --- Setup: brain factory and executables ---
brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

# --- Test Case 1: Success Path ---
echo ">>> [1] Testing success path (valid brain)"

# Create a minimal valid brain
mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki"
touch "$BRAIN_PATH/tasks/active.md"
touch "$BRAIN_PATH/tasks/done.md"
touch "$BRAIN_PATH/wiki/log.md"
cat > "$BRAIN_PATH/wiki/index.md" <<'EOF'
# Index
A valid brain.
EOF
# The brain-validate script needs to be on the path
# We assume the test runner has already installed it.
# To be safe, let's create a dummy one inside the brain factory bin
mkdir -p "$BRAIN_FACTORY_TMP/bin"
cat > "$BRAIN_FACTORY_TMP/bin/brain-validate" <<'EOF'
#!/bin/sh
echo "OK: Brain validation passed"
exit 0
EOF
chmod +x "$BRAIN_FACTORY_TMP/bin/brain-validate"
export PATH="$BRAIN_FACTORY_TMP/bin:$PATH"


# Run the cycle
brain-validate-cycle --apply --json > "$BRAIN_FACTORY_TMP/success.json"

# Assertions
if ! grep -q '"status": "success"' "$BRAIN_FACTORY_TMP/success.json"; then
  echo "FAILED: Expected status 'success' on valid brain."
  cat "$BRAIN_FACTORY_TMP/success.json"
  exit 1
fi

if ! grep -q "validate-cycle: OK" "$BRAIN_PATH/wiki/log.md"; then
  echo "FAILED: Log entry for success was not written."
  cat "$BRAIN_PATH/wiki/log.md"
  exit 1
fi
echo "    Success path OK"


# --- Test Case 2: Failure and Corrective Task ---
echo ">>> [2] Testing failure path (invalid brain) and deduplication"

# Create an invalid brain state that brain-validate will fail on.
# A dangling task reference is a good candidate.
cat > "$BRAIN_PATH/wiki/dangling.md" <<'EOF'
---
p: 3
---
This page links to a non-existent task [[t-invalid-task-ref]].
EOF

# Use a mock brain-validate that fails
cat > "$BRAIN_FACTORY_TMP/bin/brain-validate" <<'EOF'
#!/bin/sh
echo "ERROR: Invalid task reference 't-invalid-task-ref' in dangling.md"
exit 1
EOF

# Run the cycle for the first time
brain-validate-cycle --apply --json > "$BRAIN_FACTORY_TMP/failure1.json" || true

# Assertions for first failure
if ! grep -q '"status": "failure"' "$BRAIN_FACTORY_TMP/failure1.json"; then
  echo "FAILED: Expected status 'failure' on invalid brain."
  cat "$BRAIN_FACTORY_TMP/failure1.json"
  exit 1
fi

if ! grep -q 'source: validate-cycle:failure' "$BRAIN_PATH/tasks/active.md"; then
  echo "FAILED: Corrective task was not created."
  cat "$BRAIN_PATH/tasks/active.md"
  exit 1
fi

task_count_before=$(grep -c 'source: validate-cycle:failure' "$BRAIN_PATH/tasks/active.md")
if [ "$task_count_before" -ne 1 ]; then
    echo "FAILED: Expected exactly 1 corrective task, found $task_count_before."
    exit 1
fi
echo "    Failure and task creation OK"

# Integrity: the corrective MUST be a well-formed Brain task line, and the
# queue must still parse after it is appended (it protects validation, not breaks it).
if ! grep -qE "^- \[ \] \[P1\] t-[0-9-]+-validate-cycle-fix — " "$BRAIN_PATH/tasks/active.md"; then
  echo "FAILED: corrective is not a well-formed Brain task line"
  cat "$BRAIN_PATH/tasks/active.md"
  exit 1
fi
if ! brain-task list >/dev/null 2>&1; then
  echo "FAILED: active.md no longer parses (brain-task list) after corrective append"
  exit 1
fi
echo "    Corrective is well-formed and queue still parses OK"

# --- Test Case 3: Deduplication ---
echo ">>> [3] Testing task deduplication"
# Run the cycle a second time
brain-validate-cycle --apply --json > "$BRAIN_FACTORY_TMP/failure2.json" || true

# Assert that no new task was created
task_count_after=$(grep -c 'source: validate-cycle:failure' "$BRAIN_PATH/tasks/active.md")
if [ "$task_count_before" -ne "$task_count_after" ]; then
  echo "FAILED: Deduplication failed. A new task was created."
  cat "$BRAIN_PATH/tasks/active.md"
  exit 1
fi

if ! grep -q '"task_created": false' "$BRAIN_FACTORY_TMP/failure2.json"; then
  echo "FAILED: Second run should report task_created: false."
  cat "$BRAIN_FACTORY_TMP/failure2.json"
  exit 1
fi
echo "    Deduplication OK"

# --- Test Case 4: systemd install ---
echo ">>> [4] Testing systemd installation"
unit_dir="$BRAIN_FACTORY_TMP/systemd-user"
brain-validate-cycle install-systemd --unit-dir "$unit_dir" --no-enable

if [[ ! -f "$unit_dir/brain-validate-cycle.service" || ! -f "$unit_dir/brain-validate-cycle.timer" ]]; then
    echo "FAILED: systemd unit files not created."
    ls -l "$unit_dir"
    exit 1
fi

if ! grep -q "OnCalendar=daily" "$unit_dir/brain-validate-cycle.timer"; then
    echo "FAILED: Timer not set to daily."
    cat "$unit_dir/brain-validate-cycle.timer"
    exit 1
fi

if ! grep -q -- "--apply" "$unit_dir/brain-validate-cycle.service"; then
    echo "FAILED: Service not calling script with --apply."
    cat "$unit_dir/brain-validate-cycle.service"
    exit 1
fi
echo "    Systemd installation OK"


echo
echo "brain-validate-cycle test PASSED"
