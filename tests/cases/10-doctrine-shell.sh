#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-doctrine CLI"
[ -x "$HOME/.local/bin/brain-doctrine" ] || { echo "FAILED: brain-doctrine not installed"; exit 1; }
brain-doctrine --help > /dev/null
capture_output _bd_list 'brain-doctrine list'
grep -q "tax-boundaries" <<< "$_bd_list" || { echo "FAILED: brain-doctrine list missing tax-boundaries"; exit 1; }
capture_output _bd_show 'brain-doctrine show tax-boundaries'
grep -q "4 этапа\|ЭТАП\|accountant" <<< "$_bd_show" || { echo "FAILED: brain-doctrine show content missing"; exit 1; }
capture_output _bd_search 'brain-doctrine search "accountant"'
grep -q "tax-boundaries" <<< "$_bd_search" || { echo "FAILED: brain-doctrine search not finding tax-boundaries"; exit 1; }
brain-doctrine list --json | python3 -c "import json,sys; d=json.load(sys.stdin); assert len(d['doctrines']) >= 2, f'Expected >=2 doctrines, got {d}'" || { echo "FAILED: brain-doctrine list --json invalid"; exit 1; }
brain-doctrine show tax-boundaries --json | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'content' in d, f'Missing content: {d}'" || { echo "FAILED: brain-doctrine show --json missing content"; exit 1; }
brain-doctrine search "accountant" --json | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('results'), f'No results: {d}'" || { echo "FAILED: brain-doctrine search --json no results"; exit 1; }

echo ">>> Verifying brain-shell --once mode"
capture_output _sh_status 'brain-shell --once status'
grep -q "Brain:" <<< "$_sh_status" || { echo "FAILED: brain-shell --once status missing Brain header"; exit 1; }
brain-shell --once tasks > /dev/null
brain-shell --once locks > /dev/null
brain-shell --once council > /dev/null
brain-shell --once "dashboard export" > /dev/null
[ -f "$BRAIN_PATH/wiki/_views/brain-dashboard.html" ] || { echo "FAILED: brain-shell dashboard export did not create HTML"; exit 1; }
capture_output _sh_search 'brain-shell --once "search rarebrainterm"'
grep -q "wiki/search-topic.md" <<< "$_sh_search" || { echo "FAILED: brain-shell search did not find search-topic"; exit 1; }

echo ">>> Verifying brain-shell write actions with --yes"
# Add a task for write-action tests
brain-task add "Smoke Shell Write" --role developer --prio P1 > /dev/null
_shell_wid=$(grep "Smoke Shell Write" "$BRAIN_PATH/tasks/active.md" | grep -oE "t-[0-9-]+-smoke-shell-write" | head -1)
[ -n "$_shell_wid" ] || { echo "FAILED: could not create task for shell write test"; exit 1; }

# Without --yes: write to closed stdin → Aborted (EOFError → False → "Aborted.")
capture_output _sh_take_noyes 'echo "" | brain-shell --once "take $_shell_wid --as smoke-agent" 2>/dev/null'
grep -q "Aborted" <<< "$_sh_take_noyes" || { echo "FAILED: shell take without --yes should print Aborted"; exit 1; }
# Task should NOT be taken
! grep -q "\[~\].*$_shell_wid" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: task was taken without confirmation"; exit 1; }

# With --yes: take should succeed
capture_output _sh_take_yes 'brain-shell --yes --once "take $_shell_wid --as smoke-agent" 2>/dev/null'
grep -qiE "took|took $_shell_wid" <<< "$_sh_take_yes" || { echo "FAILED: shell take --yes did not succeed"; exit 1; }
[ -f "$BRAIN_PATH/.locks/$_shell_wid/owner" ] || { echo "FAILED: lock not created by shell take --yes"; exit 1; }

# Without --yes: complete on stdin empty → Aborted
capture_output _sh_complete_noyes 'echo "" | brain-shell --once "complete $_shell_wid --as smoke-agent" 2>/dev/null'
grep -q "Aborted" <<< "$_sh_complete_noyes" || { echo "FAILED: shell complete without --yes should print Aborted"; exit 1; }
# Still in-progress
grep -q "\[~\].*$_shell_wid" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: task should still be in-progress after aborted complete"; exit 1; }

# With --yes: complete
brain-shell --yes --once "complete $_shell_wid --as smoke-agent" 2>/dev/null || { echo "FAILED: shell complete --yes failed"; exit 1; }
grep -q "$_shell_wid" "$BRAIN_PATH/tasks/done.md" || { echo "FAILED: task not in done.md after shell complete --yes"; exit 1; }

# --yes flag shows up in argparse help
capture_output _sh_help 'brain-shell --help'
grep -q "\-\-yes" <<< "$_sh_help" || { echo "FAILED: --yes not in brain-shell --help"; exit 1; }
echo "brain-shell write actions --yes OK"

