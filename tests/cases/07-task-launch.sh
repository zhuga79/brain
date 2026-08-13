#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-task take on missing task"
set +e
brain-task take t-missing --as test-agent > /dev/null 2>&1
exit_code=$?
set -e
[ "$exit_code" -ne 0 ] || { echo "FAILED: brain-task take on missing task should fail"; exit 1; }
[ ! -d "$BRAIN_PATH/.locks/t-missing" ] || { echo "FAILED: Lock directory exists for missing task"; exit 1; }
! grep -q "t-missing" "$BRAIN_PATH/wiki/log.md" || { echo "FAILED: Log contains missing task entry"; exit 1; }

echo ">>> Verifying brain-launch --dry-run"
brain_task_add_out=$(brain-task add "Test council" --role architect --mode council --prio P1)
tid=$(echo "$brain_task_add_out" | grep -oE "t-[0-9-]+-test-council")
[ -n "$tid" ] || { echo "FAILED: Could not parse council task id"; exit 1; }

tmp_active="$BRAIN_PATH/tasks/active.md.tmp"
awk -v id="$tid" '
    { print }
    $0 ~ id { in_task = 1; next }
    in_task && /role:.*mode: council/ {
        print "      council: [architect, developer]"
        in_task = 0
    }
' "$BRAIN_PATH/tasks/active.md" > "$tmp_active"
mv "$tmp_active" "$BRAIN_PATH/tasks/active.md"

# Маршрутизация роль → команда берётся из config/routing.json через
# brain-provider cli: bash-слой больше не хранит собственную копию политики.
mkdir -p "$BRAIN_PATH/config"
cat > "$BRAIN_PATH/config/routing.json" <<'EOF'
{
  "version": 2,
  "defaults": { "cli": "claude" },
  "roles": {
    "architect": [ { "rank": 1, "provider": "codex", "model": "test", "command": "codex" } ],
    "developer": [ { "rank": 1, "provider": "gemini", "model": "test-model", "command": "gemini -m test-model" } ]
  }
}
EOF

BRAIN_DISABLE_SKILL_ROUTING=1 brain-launch "$tid" --dry-run > /tmp/brain_launch_dryrun.log
[ ! -d "$BRAIN_PATH/council/$tid" ] || { echo "FAILED: Council directory created on --dry-run"; exit 1; }

# Check architect (non-gemini) -> pipe
grep -A 1 "architect  →  codex" /tmp/brain_launch_dryrun.log | grep -q "brain-run .* | codex" || {
    echo "FAILED: dry-run architect command mismatch"
    cat /tmp/brain_launch_dryrun.log
    exit 1
}

# Check developer (gemini) -> -p
grep -A 1 "developer  →  gemini -m test-model" /tmp/brain_launch_dryrun.log | grep -q "gemini -m test-model -p" || {
    echo "FAILED: dry-run developer command mismatch (Gemini -p missing)"
    cat /tmp/brain_launch_dryrun.log
    exit 1
}
grep -A 1 "developer  →  gemini -m test-model" /tmp/brain_launch_dryrun.log | grep -q "\$prompt" || {
    echo "FAILED: dry-run developer command mismatch (\$prompt missing)"
    cat /tmp/brain_launch_dryrun.log
    exit 1
}
echo "brain-launch --dry-run content OK"

echo ">>> Verifying brain-launch --watch --dry-run"
BRAIN_DISABLE_SKILL_ROUTING=1 brain-launch "$tid" --watch --dry-run > /tmp/brain_watch_dryrun.log 2>&1 || { echo "FAILED: brain-launch --watch --dry-run exited non-zero"; exit 1; }
grep -qi "watch plan\|Watch plan\|watch" /tmp/brain_watch_dryrun.log || { echo "FAILED: brain-launch --watch --dry-run missing watch plan output"; exit 1; }
grep -qi "session\|brain-" /tmp/brain_watch_dryrun.log || { echo "FAILED: brain-launch --watch --dry-run missing session name"; exit 1; }
[ ! -d "$BRAIN_PATH/council/$tid" ] || { echo "FAILED: Council directory created on --watch --dry-run"; exit 1; }

echo ">>> Verifying brain-launch --watch --auto-next --dry-run"
BRAIN_DISABLE_SKILL_ROUTING=1 brain-launch "$tid" --watch --auto-next --dry-run > /tmp/brain_autonext_dryrun.log 2>&1 || { echo "FAILED: brain-launch --watch --auto-next --dry-run exited non-zero"; exit 1; }
grep -qi "auto-next\|Auto-next" /tmp/brain_autonext_dryrun.log || { echo "FAILED: --auto-next --dry-run missing auto-next plan output"; exit 1; }
grep -qi "current task\|Current task" /tmp/brain_autonext_dryrun.log || { echo "FAILED: --auto-next --dry-run missing current task"; exit 1; }
grep -qi "lock protocol\|Lock protocol" /tmp/brain_autonext_dryrun.log || { echo "FAILED: --auto-next --dry-run missing lock protocol"; exit 1; }
grep -qi "DRY-RUN" /tmp/brain_autonext_dryrun.log || { echo "FAILED: --auto-next --dry-run missing DRY-RUN marker"; exit 1; }
[ ! -d "$BRAIN_PATH/council/$tid" ] || { echo "FAILED: Council created by --auto-next --dry-run"; exit 1; }
echo "brain-launch --watch --auto-next --dry-run OK"

echo ">>> Verifying brain-launch --handoff-on-limit dry-run"
BRAIN_DISABLE_SKILL_ROUTING=1 brain-launch "$tid" --dry-run --handoff-on-limit > /tmp/brain_launch_handoff_dryrun.log 2>&1 || { echo "FAILED: brain-launch --handoff-on-limit --dry-run exited non-zero"; exit 1; }
grep -q "brain-handoff run" /tmp/brain_launch_handoff_dryrun.log || { echo "FAILED: --handoff-on-limit dry-run missing brain-handoff wrapper"; exit 1; }
grep -q -- "--to-role developer" /tmp/brain_launch_handoff_dryrun.log || { echo "FAILED: --handoff-on-limit dry-run missing role handoff"; exit 1; }
grep -q "gemini -m test-model" /tmp/brain_launch_handoff_dryrun.log || { echo "FAILED: --handoff-on-limit dry-run lost Gemini command"; exit 1; }
echo "brain-launch --handoff-on-limit dry-run OK"

echo ">>> [Phase 7] Verifying brain-launch injection protection"
# PoC: shell-injected task-id must be rejected
set +e
_inj_out=$(brain-launch 't-x;touch /tmp/pwn' --dry-run 2>&1); inj_rc=$?
set -e
[ "$inj_rc" -ne 0 ] || { echo "FAILED: brain-launch accepted injected task-id"; exit 1; }
echo "$_inj_out" | grep -qiE "invalid|reject|недопустим" || { echo "FAILED: injection error unclear: $_inj_out"; exit 1; }
[ ! -f /tmp/pwn ] || { echo "FAILED: injection payload executed"; rm -f /tmp/pwn; exit 1; }

# PoC: shell-injected role name must be rejected
mkdir -p "$BRAIN_PATH/council/t-inject-role-test"
cat > "$BRAIN_PATH/council/t-inject-role-test/architect.md" <<EOF
---
task: t-inject-role-test
role: architect
agent: test
model: test
written: 2026-05-03T10:00:00Z
---

## Position
Test.
## Recommendation
Test.
EOF
# Manually create a task with an injected role in council field
_tmp_active_inj="$BRAIN_PATH/tasks/active.md.injtest"
cp "$BRAIN_PATH/tasks/active.md" "$_tmp_active_inj"
cat >> "$BRAIN_PATH/tasks/active.md" <<EOF

- [ ] [P1] t-inject-role-test — Injection role test
      role: architect   mode: council
      council: [architect;touch /tmp/pwn2]
EOF
set +e
_inj2_out=$(brain-launch 't-inject-role-test' --dry-run 2>&1); inj2_rc=$?
set -e
[ "$inj2_rc" -ne 0 ] || { echo "FAILED: brain-launch accepted injected role name"; exit 1; }
echo "$_inj2_out" | grep -qiE "invalid|reject|недопустим" || { echo "FAILED: role injection error unclear: $_inj2_out"; exit 1; }
[ ! -f /tmp/pwn2 ] || { echo "FAILED: role injection payload executed"; rm -f /tmp/pwn2; exit 1; }

# Restore active.md
mv "$_tmp_active_inj" "$BRAIN_PATH/tasks/active.md"
rm -rf "$BRAIN_PATH/council/t-inject-role-test"
echo "brain-launch injection protection OK"

echo ">>> Verifying brain-task show/list --json"
# 1. show found task
brain-task show "$tid" --json > /tmp/task_show.json
python3 -c "import json, sys; d=json.load(open('/tmp/task_show.json')); assert d['ok'] == True; assert d['task']['id'] == '$tid'"
# 2. show missing task
set +e
brain-task show t-missing-xyz --json > /tmp/task_show_missing.json 2>&1
show_missing_rc=$?
set -e
[ "$show_missing_rc" -ne 0 ] || { echo "FAILED: brain-task show missing should fail"; exit 1; }
python3 -c "import json, sys; d=json.load(open('/tmp/task_show_missing.json')); assert d['ok'] == False; assert 'not found' in d['error']"

# 3. list --json
brain-task list --json > /tmp/task_list.json
python3 -c "import json, sys; d=json.load(open('/tmp/task_list.json')); assert d['ok'] == True; assert isinstance(d['tasks'], list); assert any(t['id'] == '$tid' for t in d['tasks'])"

# 4. list --role --json
brain-task list --role architect --json > /tmp/task_list_role.json
python3 -c "import json, sys; d=json.load(open('/tmp/task_list_role.json')); assert all(t.get('role') == 'architect' for t in d['tasks'])"

echo "brain-task show/list --json OK"
