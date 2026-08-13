#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-council check guardrails"
# Create a minimal council with valid role files and run check
_ctid="t-smoke-council-check"
mkdir -p "$BRAIN_PATH/council/$_ctid"
cat > "$BRAIN_PATH/council/$_ctid/architect.md" <<EOF
---
task: $_ctid
role: architect
agent: smoke-agent-test
model: test-model
written: 2026-05-03T10:00:00Z
---

## Position

Test position content.

## Reasoning

Test reasoning.

## Risks / Open questions

None.

## Recommendation

Do the thing.
EOF
cat > "$BRAIN_PATH/council/$_ctid/reviewer.md" <<EOF
---
task: $_ctid
role: reviewer
agent: smoke-agent-test
model: test-model
written: 2026-05-03T10:05:00Z
---

## Position

Reviewer position.

## Reasoning

Reasoning here.

## Risks / Open questions

None.

## Recommendation

Approve it.
EOF
brain-council check "$_ctid" > /tmp/_council_check.log 2>&1 || { echo "FAILED: brain-council check failed for valid council"; cat /tmp/_council_check.log; exit 1; }
grep -q "status: OK" /tmp/_council_check.log || { echo "FAILED: brain-council check missing 'status: OK'"; cat /tmp/_council_check.log; exit 1; }
grep -q "WARN: solo council" /tmp/_council_check.log || { echo "FAILED: brain-council check missing solo-council WARN"; cat /tmp/_council_check.log; exit 1; }
# Test error detection: agent TODO
_ctid2="t-smoke-council-check-fail"
mkdir -p "$BRAIN_PATH/council/$_ctid2"
cat > "$BRAIN_PATH/council/$_ctid2/architect.md" <<EOF
---
task: $_ctid2
role: architect
agent: TODO
model: TODO
written: TODO
---

## Position

## Recommendation
EOF
brain-council check "$_ctid2" > /tmp/_council_check2.log 2>&1 && { echo "FAILED: brain-council check should have failed for TODO council"; exit 1; } || true
grep -q "status: FAIL" /tmp/_council_check2.log || { echo "FAILED: brain-council check missing 'status: FAIL' for invalid council"; cat /tmp/_council_check2.log; exit 1; }
rm -rf "$BRAIN_PATH/council/$_ctid" "$BRAIN_PATH/council/$_ctid2"
echo "brain-council check guardrails OK"

echo ">>> Verifying brain-prd init and commit"
brain-task add "Test PRD" --role architect --mode prd --prio P1 > /dev/null
pid=$(grep "Test PRD" "$BRAIN_PATH/tasks/active.md" | grep -oE "t-[0-9-]+-test-prd" | head -1)
brain-prd init "$pid" > /dev/null
cat >> "$BRAIN_PATH/prd/$pid.md" <<EOF

## Subtasks

- [ ] [P1] s1 — Subtask 1
      role: developer
      mode: solo
      acceptance: ok
- [ ] [P2] s2 — Subtask 2
      role: developer
      mode: solo
      depends_on: [s1]
      acceptance: ok
EOF
before_hash=$(sha256sum "$BRAIN_PATH/tasks/active.md" | awk '{print $1}')
brain-prd dry-run "$pid" > /tmp/brain_prd_dry_run.log
after_hash=$(sha256sum "$BRAIN_PATH/tasks/active.md" | awk '{print $1}')
[ "$before_hash" = "$after_hash" ] || { echo "FAILED: brain-prd dry-run modified active.md"; exit 1; }
grep -q "DRY-RUN" /tmp/brain_prd_dry_run.log || { echo "FAILED: brain-prd dry-run missing marker"; exit 1; }
grep -q "$pid-s1" /tmp/brain_prd_dry_run.log || { echo "FAILED: brain-prd dry-run missing normalized s1"; exit 1; }
grep -q "depends_on: \\[$pid-s1\\]" /tmp/brain_prd_dry_run.log || { echo "FAILED: brain-prd dry-run missing normalized deps"; exit 1; }
grep -q "mode: solo" /tmp/brain_prd_dry_run.log || { echo "FAILED: brain-prd dry-run missing mode"; exit 1; }
brain-prd commit "$pid" > /dev/null
grep -q "$pid-s1" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: Subtask 1 not found"; exit 1; }
grep -q "$pid-s2" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: Subtask 2 not found"; exit 1; }

echo ">>> Verifying brain-run for tax-advisor includes doctrine"
brain_run_out=$(brain-run --role tax-advisor --task "$pid-s1")
grep -Eq "4 этапа|4-stage doctrine|этап \\(1.?4\\)" <<< "$brain_run_out" || { echo "FAILED: Doctrine not found in brain-run output"; exit 1; }

echo ">>> [Regression] Verifying hyphenated task ID exact matching"
cat > "$BRAIN_PATH/tasks/active.md" <<EOF
# Active tasks

- [ ] [P2] t-dependent — Task depending on t-parent
      role: developer
      depends_on: [t-parent]
EOF
cat > "$BRAIN_PATH/tasks/done.md" <<EOF
# Done tasks

- [x] [P2] t-parent-child — Completed task with longer id
      role: developer
      completed: 2026-05-02T00:00:00Z
EOF

next_out=$(brain-task next --role developer | head -n 1)
if echo "$next_out" | grep -q "t-dependent"; then
    echo "FAILED: t-dependent is available but its dependency t-parent is NOT done (matched t-parent-child incorrectly)"
    exit 1
fi
cat >> "$BRAIN_PATH/tasks/done.md" <<EOF

- [x] [P2] t-parent — Exact completed dependency
      role: developer
      completed: 2026-05-02T00:00:00Z
EOF
brain-task next --role developer | grep -q "t-dependent" || {
    echo "FAILED: t-dependent did not become available after exact dependency t-parent completed"
    exit 1
}
