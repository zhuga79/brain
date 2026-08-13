#!/usr/bin/env bash
# Integration test for brain-provider-probe (Tier-1 provider health cycle).
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-provider-probe"

brain_factory
mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki"
printf '# Active Tasks\n' > "$BRAIN_PATH/tasks/active.md"
printf '# Done\n' > "$BRAIN_PATH/tasks/done.md"
printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"

# Mock brain-provider: 'probe' succeeds; 'status --json' emits $MOCK_STATUS (default healthy).
mockbin="$BRAIN_FACTORY_TMP/mockbin"; mkdir -p "$mockbin"
cat > "$mockbin/brain-provider" <<'PY'
#!/usr/bin/env python3
import json, os, sys
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "probe":
    print(json.dumps({"ok": True, "probed_count": 1})); sys.exit(0)
if cmd == "status":
    print(os.environ.get("MOCK_STATUS", json.dumps({
        "roles": {"developer": {"preferred": {"key": "codex/gpt", "status": "available"}}}})))
    sys.exit(0)
sys.stderr.write(f"unknown: {sys.argv[1:]}\n"); sys.exit(2)
PY
chmod +x "$mockbin/brain-provider"
# Mock wins over real brain-provider; real brain-provider-probe comes from runtime/bin.
export PATH="$mockbin:$PROJECT_ROOT/runtime/bin:$PATH"

parses() { PYTHONPATH="$PROJECT_ROOT/runtime/lib" python3 -c "import sys,brain_task_parser as p; p.find_blocks(open(sys.argv[1]).read())" "$1"; }

# (a) all healthy -> --apply logs healthy, no corrective
brain-provider-probe --apply >/dev/null 2>&1 || true
grep -q "All providers healthy" "$BRAIN_PATH/wiki/log.md" || { echo "FAILED: healthy not logged"; exit 1; }
grep -q "source: provider-probe:down" "$BRAIN_PATH/tasks/active.md" && { echo "FAILED: corrective created while healthy"; exit 1; }
echo "OK: healthy path"

# (b) a provider down -> --apply appends a well-formed corrective; queue still parses
export MOCK_STATUS='{"roles":{"developer":{"preferred":{"key":"codex/gpt","status":"available"}},"pm":{"preferred":{"key":"claude/x","status":"error"}}}}'
brain-provider-probe --apply >/dev/null 2>&1 || true
grep -qE "^- \[ \] \[P1\] t-[0-9-]+-provider-down-fix — " "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: corrective not well-formed"; cat "$BRAIN_PATH/tasks/active.md"; exit 1; }
grep -q "source: provider-probe:down" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: missing source"; exit 1; }
grep -q "role: pm" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: missing role"; exit 1; }
parses "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: active.md no longer parses"; exit 1; }
echo "OK: down path appends well-formed corrective"

# (c) dedup on second run
before=$(grep -c "source: provider-probe:down" "$BRAIN_PATH/tasks/active.md")
brain-provider-probe --apply >/dev/null 2>&1 || true
after=$(grep -c "source: provider-probe:down" "$BRAIN_PATH/tasks/active.md")
[ "$before" -eq "$after" ] && [ "$after" -eq 1 ] || { echo "FAILED: dedup ($before -> $after)"; exit 1; }
echo "OK: dedup"

# (d) --dry-run writes nothing
log_before=$(wc -c < "$BRAIN_PATH/wiki/log.md"); tasks_before=$(wc -c < "$BRAIN_PATH/tasks/active.md")
brain-provider-probe --dry-run >/dev/null 2>&1 || true
[ "$(wc -c < "$BRAIN_PATH/wiki/log.md")" -eq "$log_before" ] || { echo "FAILED: dry-run wrote log"; exit 1; }
[ "$(wc -c < "$BRAIN_PATH/tasks/active.md")" -eq "$tasks_before" ] || { echo "FAILED: dry-run wrote tasks"; exit 1; }
echo "OK: dry-run writes nothing"

# (e) install-systemd -> hourly timer + --apply service
unit_dir="$BRAIN_FACTORY_TMP/systemd-user"
brain-provider-probe install-systemd --unit-dir "$unit_dir" --no-enable >/dev/null 2>&1
[ -f "$unit_dir/brain-provider-probe.service" ] && [ -f "$unit_dir/brain-provider-probe.timer" ] || { echo "FAILED: unit files missing"; exit 1; }
grep -q "OnCalendar=hourly" "$unit_dir/brain-provider-probe.timer" || { echo "FAILED: timer not hourly"; exit 1; }
grep -q -- "--apply" "$unit_dir/brain-provider-probe.service" || { echo "FAILED: service missing --apply"; exit 1; }
echo "OK: systemd install"

echo "brain-provider-probe test PASSED"
