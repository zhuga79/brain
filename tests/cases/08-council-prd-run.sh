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

echo ">>> Verifying brain-council resolves split-root teams and roles"
(
brain_factory
export BRAIN_SYSTEM_PATH="$PROJECT_ROOT"
mkdir -p "$BRAIN_PATH"/{tasks,wiki,council,raw,prd,teams,.locks}
cat > "$BRAIN_PATH/tasks/active.md" <<'EOF'
# Active tasks

- [ ] [P1] t-split-system-team — System team
      role: developer
      mode: council
      council: [team:engineering]

- [ ] [P1] t-split-data-team — Data team
      role: developer
      mode: council
      council: [team:insurance-fraud]

- [ ] [P1] t-split-direct — Direct roles
      role: developer
      mode: council
      council: [developer, reviewer]

- [ ] [P1] t-split-unknown-team — Unknown team
      role: developer
      mode: council
      council: [team:no-such-team]

- [ ] [P1] t-split-unknown-role — Unknown role
      role: developer
      mode: council
      council: [developer, no-such-role]
EOF
cat > "$BRAIN_PATH/tasks/done.md" <<'EOF'
# Done tasks
EOF
cat > "$BRAIN_PATH/wiki/log.md" <<'EOF'
# Log
EOF
cat > "$BRAIN_PATH/teams/insurance-fraud.md" <<'EOF'
---
title: Team insurance-fraud
type: team
roles: [reviewer]
---
EOF

"$PROJECT_ROOT/runtime/bin/brain-council" start t-split-system-team > /tmp/council-system.log 2>&1 || {
  echo "FAILED: system team did not resolve from split-root"
  cat /tmp/council-system.log
  exit 1
}
for role in architect developer reviewer; do
  [ -f "$BRAIN_PATH/council/t-split-system-team/$role.md" ] || {
    echo "FAILED: missing system team opinion template for $role"
    exit 1
  }
done
grep -q "roles: .*architect.*developer.*reviewer" /tmp/council-system.log || {
  echo "FAILED: system team output did not list resolved roles"
  cat /tmp/council-system.log
  exit 1
}

"$PROJECT_ROOT/runtime/bin/brain-council" start t-split-data-team > /tmp/council-data.log 2>&1 || {
  echo "FAILED: data team did not resolve with local precedence"
  cat /tmp/council-data.log
  exit 1
}
[ -f "$BRAIN_PATH/council/t-split-data-team/reviewer.md" ] || {
  echo "FAILED: data team reviewer template missing"
  exit 1
}
[ ! -f "$BRAIN_PATH/council/t-split-data-team/architect.md" ] || {
  echo "FAILED: data team incorrectly fell through to system engineering team"
  exit 1
}

"$PROJECT_ROOT/runtime/bin/brain-council" start t-split-direct > /tmp/council-direct.log 2>&1 || {
  echo "FAILED: direct split-root roles did not materialize"
  cat /tmp/council-direct.log
  exit 1
}
for role in developer reviewer; do
  [ -f "$BRAIN_PATH/council/t-split-direct/$role.md" ] || {
    echo "FAILED: missing direct council template for $role"
    exit 1
  }
done

set +e
unknown_team_out=$("$PROJECT_ROOT/runtime/bin/brain-council" start t-split-unknown-team 2>&1)
unknown_team_rc=$?
set -e
[ "$unknown_team_rc" -ne 0 ] || {
  echo "FAILED: unknown team should fail closed"
  exit 1
}
grep -qi "no such team" <<< "$unknown_team_out" || {
  echo "FAILED: unknown team error not surfaced"
  echo "$unknown_team_out"
  exit 1
}
grep -qi "council started" <<< "$unknown_team_out" && {
  echo "FAILED: unknown team printed misleading started message"
  echo "$unknown_team_out"
  exit 1
}
[ ! -d "$BRAIN_PATH/council/t-split-unknown-team" ] || {
  echo "FAILED: unknown team left partial council directory"
  exit 1
}

set +e
unknown_role_out=$("$PROJECT_ROOT/runtime/bin/brain-council" start t-split-unknown-role 2>&1)
unknown_role_rc=$?
set -e
[ "$unknown_role_rc" -ne 0 ] || {
  echo "FAILED: unknown role should fail closed"
  exit 1
}
grep -qi "no role file" <<< "$unknown_role_out" || {
  echo "FAILED: unknown role error not surfaced"
  echo "$unknown_role_out"
  exit 1
}
grep -qi "council started" <<< "$unknown_role_out" && {
  echo "FAILED: unknown role printed misleading started message"
  echo "$unknown_role_out"
  exit 1
}
[ ! -d "$BRAIN_PATH/council/t-split-unknown-role" ] || {
  echo "FAILED: unknown role left partial council directory"
  exit 1
}
echo "brain-council split-root resolution OK"
)

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
# The prd-commit audit line is written by prdfile inside the queue transaction,
# not appended by the CLI afterwards (t-2026-08-14-prd-decompose-log-transaction).
audit_count=$(grep -cE "^## \[[^]]*\] prd-commit \| $pid \|" "$BRAIN_PATH/wiki/log.md" || true)
[ "$audit_count" = "1" ] || { echo "FAILED: prd-commit not audited exactly once (got $audit_count)"; cat "$BRAIN_PATH/wiki/log.md"; exit 1; }
grep -qE "^## \[[^]]*\] prd-commit \| $pid \|.* sig=[0-9a-f]+$" "$BRAIN_PATH/wiki/log.md" || { echo "FAILED: prd-commit audit line missing sig"; exit 1; }

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

capture_output next_full 'brain-task next --role developer'
next_out=$(head -n 1 <<< "$next_full")
if grep -q "t-dependent" <<< "$next_out"; then
    echo "FAILED: t-dependent is available but its dependency t-parent is NOT done (matched t-parent-child incorrectly)"
    exit 1
fi
cat >> "$BRAIN_PATH/tasks/done.md" <<EOF

- [x] [P2] t-parent — Exact completed dependency
      role: developer
      completed: 2026-05-02T00:00:00Z
EOF
capture_output next_full2 'brain-task next --role developer'
grep -q "t-dependent" <<< "$next_full2" || {
    echo "FAILED: t-dependent did not become available after exact dependency t-parent completed"
    exit 1
}
