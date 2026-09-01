#!/usr/bin/env bash
# e2e-orchestration.sh — End-to-end Brain orchestration drill
#
# Scenario: task add → take → council start → write opinions → synthesize →
#           council check → complete
# Verifies artifacts exist and log entries are written at each step.
#
# Usage:
#   BRAIN_PATH=/path/to/brain bash tests/e2e-orchestration.sh
set -euo pipefail

BRAIN_PATH="${BRAIN_PATH:-$HOME/brain}"
AGENT_ID="e2e-agent-$$"
E2E_TASK_ID=""

cleanup() {
  if [ -n "$E2E_TASK_ID" ]; then
    brain-lock release "$E2E_TASK_ID" --as "$AGENT_ID" 2>/dev/null || true
    # Remove test task from active/done if present
    sed -i "/$E2E_TASK_ID/d" "$BRAIN_PATH/tasks/active.md" 2>/dev/null || true
    sed -i "/$E2E_TASK_ID/d" "$BRAIN_PATH/tasks/done.md" 2>/dev/null || true
    rm -rf "$BRAIN_PATH/council/$E2E_TASK_ID" 2>/dev/null || true
    rm -rf "$BRAIN_PATH/.locks/$E2E_TASK_ID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

pass() { echo "[PASS] $*"; }
fail() { echo "[FAIL] $*" >&2; exit 1; }

echo "=== E2E Orchestration Drill ==="
echo "Brain: $BRAIN_PATH"
echo "Agent: $AGENT_ID"
echo

# ── Step 1: Add task ──────────────────────────────────────────────────────────
echo "--- Step 1: brain-task add ---"
add_out=$(brain-task add "E2E Orchestration Test" --role architect --mode council --prio P1)
E2E_TASK_ID=$(echo "$add_out" | grep -oE "t-[0-9-]+-e2e-orchestration-test" | head -1)
[ -n "$E2E_TASK_ID" ] || fail "Could not parse task id from: $add_out"
grep -q "$E2E_TASK_ID" "$BRAIN_PATH/tasks/active.md" || fail "Task $E2E_TASK_ID not in active.md"
pass "Task created: $E2E_TASK_ID"

# Inject council field into active.md
tmp_active=$(mktemp)
awk -v id="$E2E_TASK_ID" '
    { print }
    $0 ~ id { in_task = 1; next }
    in_task && /role:.*mode: council/ {
        print "      council: [architect, reviewer]"
        in_task = 0
    }
' "$BRAIN_PATH/tasks/active.md" > "$tmp_active"
mv "$tmp_active" "$BRAIN_PATH/tasks/active.md"
pass "Council field injected"

# ── Step 2: Take task ─────────────────────────────────────────────────────────
echo "--- Step 2: brain-task take ---"
brain-task take "$E2E_TASK_ID" --as "$AGENT_ID"
[ -f "$BRAIN_PATH/.locks/$E2E_TASK_ID/owner" ] || fail "Lock not created after take"
grep -q "\[~\].*$E2E_TASK_ID" "$BRAIN_PATH/tasks/active.md" || fail "Task not in-progress after take"
log_before=$(wc -l < "$BRAIN_PATH/wiki/log.md")
pass "Task taken, lock acquired"

# ── Step 3: Council start ─────────────────────────────────────────────────────
echo "--- Step 3: brain-council start ---"
brain-council start "$E2E_TASK_ID" > /dev/null
[ -d "$BRAIN_PATH/council/$E2E_TASK_ID" ] || fail "Council directory not created"
[ -f "$BRAIN_PATH/council/$E2E_TASK_ID/architect.md" ] || fail "architect.md not created"
[ -f "$BRAIN_PATH/council/$E2E_TASK_ID/reviewer.md" ] || fail "reviewer.md not created"
pass "Council started, skeleton files created"

# ── Step 4: Write role opinions ───────────────────────────────────────────────
echo "--- Step 4: Write role opinions ---"
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

cat > "$BRAIN_PATH/council/$E2E_TASK_ID/architect.md" <<EOF
---
task: $E2E_TASK_ID
role: architect
agent: $AGENT_ID
model: claude-sonnet-4-6
written: $NOW
---

## Position

Use file-based state, no external dependencies.

## Reasoning

Brain is filesystem-first. Adding a database would break portability.

## Risks / Open questions

None significant.

## Recommendation

Proceed with file-based implementation.
EOF

cat > "$BRAIN_PATH/council/$E2E_TASK_ID/reviewer.md" <<EOF
---
task: $E2E_TASK_ID
role: reviewer
agent: $AGENT_ID
model: claude-sonnet-4-6
written: $NOW
---

## Position

Agree with file-based approach. Lock protocol is sufficient.

## Reasoning

Existing brain-lock CLI covers all concurrency cases.

## Risks / Open questions

Race conditions in concurrent writes — acceptable given CLI locking.

## Recommendation

Approve implementation as-is.
EOF

[ -f "$BRAIN_PATH/council/$E2E_TASK_ID/architect.md" ] || fail "architect.md not written"
[ -f "$BRAIN_PATH/council/$E2E_TASK_ID/reviewer.md" ] || fail "reviewer.md not written"
grep -q "agent: $AGENT_ID" "$BRAIN_PATH/council/$E2E_TASK_ID/architect.md" || fail "architect.md missing agent field"
grep -q "written: $NOW" "$BRAIN_PATH/council/$E2E_TASK_ID/architect.md" || fail "architect.md missing written field"
pass "Role opinions written"

# ── Step 5: brain-council check ───────────────────────────────────────────────
echo "--- Step 5: brain-council check ---"
check_out=$(brain-council check "$E2E_TASK_ID" 2>&1)
echo "$check_out" | grep -q "status: OK" || fail "brain-council check failed: $check_out"
pass "Council check passed"

# ── Step 6: brain-council synthesize ─────────────────────────────────────────
echo "--- Step 6: brain-council synthesize ---"
brain-council synthesize "$E2E_TASK_ID" --force > /dev/null
[ -f "$BRAIN_PATH/council/$E2E_TASK_ID/synthesis.md" ] || fail "synthesis.md not created"
pass "Synthesis skeleton created"

# Write arbiter synthesis
cat >> "$BRAIN_PATH/council/$E2E_TASK_ID/synthesis.md" <<EOF

# Arbiter note: both roles agreed on file-based approach.
EOF

# Update synthesized/arbiter fields
sed -i "s/synthesized: TODO/synthesized: $NOW/" "$BRAIN_PATH/council/$E2E_TASK_ID/synthesis.md"
sed -i "s/arbiter: TODO/arbiter: $AGENT_ID/" "$BRAIN_PATH/council/$E2E_TASK_ID/synthesis.md"
grep -q "synthesized: $NOW" "$BRAIN_PATH/council/$E2E_TASK_ID/synthesis.md" || fail "synthesis.md synthesized field not updated"
pass "Synthesis filled"

# ── Step 7: brain-council status ─────────────────────────────────────────────
echo "--- Step 7: brain-council status ---"
status_out=$(brain-council status "$E2E_TASK_ID" 2>&1)
echo "$status_out" | grep -q "architect" || fail "architect not in council status: $status_out"
echo "$status_out" | grep -q "reviewer" || fail "reviewer not in council status: $status_out"
echo "$status_out" | grep -q "synthesis.md" || fail "synthesis.md not in council status: $status_out"
pass "Council status OK"

# ── Step 8: brain-task complete ──────────────────────────────────────────────
echo "--- Step 8: brain-task complete ---"
brain-task complete "$E2E_TASK_ID" --as "$AGENT_ID" --model openai-gpt-5.4
grep -q "$E2E_TASK_ID" "$BRAIN_PATH/tasks/done.md" || fail "Task not in done.md after complete"
[ ! -f "$BRAIN_PATH/.locks/$E2E_TASK_ID/owner" ] || fail "Lock not released after complete"
log_after=$(wc -l < "$BRAIN_PATH/wiki/log.md")
[ "$log_after" -gt "$log_before" ] || fail "Log not updated after task complete"
pass "Task completed, lock released, log updated"

# ── Step 9: Artifact verification ────────────────────────────────────────────
echo "--- Step 9: Artifact verification ---"
# Council directory persists after complete
[ -d "$BRAIN_PATH/council/$E2E_TASK_ID" ] || fail "Council directory removed prematurely"
# All 3 council files present
[ -f "$BRAIN_PATH/council/$E2E_TASK_ID/architect.md" ] || fail "architect.md missing"
[ -f "$BRAIN_PATH/council/$E2E_TASK_ID/reviewer.md" ] || fail "reviewer.md missing"
[ -f "$BRAIN_PATH/council/$E2E_TASK_ID/synthesis.md" ] || fail "synthesis.md missing"
pass "All council artifacts present"

echo
echo "=== E2E Orchestration Drill: ALL STEPS PASSED ==="
