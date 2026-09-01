#!/usr/bin/env bash
# Integration test for brain-model-fleet (cyclical live-model registry).
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-model-fleet"

brain_factory
mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki"
printf '# Active Tasks\n' > "$BRAIN_PATH/tasks/active.md"
printf '# Done\n' > "$BRAIN_PATH/tasks/done.md"
printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"

registry="$BRAIN_PATH/config/model-fleet.json"
report="$BRAIN_PATH/wiki/model-fleet-report.md"

# Mock brain-provider ('probe' ok / 'status' emits $MOCK_STATUS) and CLI clients
# (claude/opencode/codex) so model discovery is hermetic under factory HOME.
mockbin="$BRAIN_FACTORY_TMP/mockbin"; mkdir -p "$mockbin"
cat > "$mockbin/brain-provider" <<'PY'
#!/usr/bin/env python3
import json, os, sys
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "probe":
    if os.environ.get("MOCK_PROBE_FAIL") == "1":
        sys.stderr.write("probe boom\n"); sys.exit(1)
    print(json.dumps({"ok": True, "probed_count": 1})); sys.exit(0)
if cmd == "status":
    print(os.environ.get("MOCK_STATUS", json.dumps({
        "roles": {"architect": {"preferred": {"key": "claude/opus", "model": "opus",
                                              "status": "available"}}}})))
    sys.exit(0)
sys.stderr.write(f"unknown: {sys.argv[1:]}\n"); sys.exit(2)
PY
cat > "$mockbin/opencode" <<'SH'
#!/usr/bin/env bash
case "${1:-}" in
  models) printf '%s\n' "opencode/big-pickle" "opencode/claude-sonnet-5" "opencode/claude-opus-5";;
  --version) echo "opencode 1.18.25";;
  *) exit 2;;
esac
SH
cat > "$mockbin/claude" <<'SH'
#!/usr/bin/env bash
case "${1:-}" in
  --version) echo "2.1.251 (Claude Code)";;
  *) exit 2;;
esac
SH
cat > "$mockbin/codex" <<'SH'
#!/usr/bin/env bash
case "${1:-}" in
  --version) echo "codex 0.36";;
  *) exit 2;;
esac
SH
chmod +x "$mockbin"/*
export PATH="$mockbin:$PROJECT_ROOT/runtime/bin:$PATH"

parses() { PYTHONPATH="$PROJECT_ROOT/runtime/lib" python3 -c "import sys,brain_task_parser as p; p.find_blocks(open(sys.argv[1]).read())" "$1"; }

# (a) --dry-run writes nothing: no registry, no log line, no corrective
log_before=$(wc -c < "$BRAIN_PATH/wiki/log.md")
brain-model-fleet --dry-run >/dev/null 2>&1
[ ! -e "$registry" ] || { echo "FAILED: dry-run wrote registry"; exit 1; }
[ "$(wc -c < "$BRAIN_PATH/wiki/log.md")" -eq "$log_before" ] || { echo "FAILED: dry-run wrote log"; exit 1; }
echo "OK: dry-run writes nothing"

# (b) healthy --apply -> registry + report written, log OK, no corrective
brain-model-fleet --apply >/dev/null 2>&1
python3 - "$registry" <<'PY' || { echo "FAILED: registry content"; exit 1; }
import json, sys
r = json.load(open(sys.argv[1]))
assert r["version"] == 1 and r["updated_utc"], "registry shape"
models = r["clients"]["opencode"]["models"]
assert "opencode/claude-sonnet-5" in models, f"live id missing: {models}"
assert r["roles"]["architect"]["preferred"] == "claude/opus"
PY
grep -q "Model Fleet Report" "$report" || { echo "FAILED: report not regenerated"; exit 1; }
grep -q "OK - registry updated" "$BRAIN_PATH/wiki/log.md" || { echo "FAILED: healthy not logged"; exit 1; }
grep -q "source: model-fleet:refresh-failure" "$BRAIN_PATH/tasks/active.md" && { echo "FAILED: corrective while healthy"; exit 1; }
echo "OK: healthy path"

# (c) broken probe -> --apply exits non-zero, appends well-formed corrective, output preserved
export MOCK_PROBE_FAIL=1
if brain-model-fleet --apply >/dev/null 2>&1; then echo "FAILED: broken probe exited 0"; exit 1; fi
unset MOCK_PROBE_FAIL
grep -qE "^- \[ \] \[P1\] t-[0-9-]+-model-fleet-refresh-fix — " "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: corrective not well-formed"; cat "$BRAIN_PATH/tasks/active.md"; exit 1; }
grep -q "source: model-fleet:refresh-failure" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: missing source"; exit 1; }
grep -q "role: sre" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: missing role"; exit 1; }
grep -q "probe boom" "$BRAIN_PATH/wiki/log.md" || { echo "FAILED: failure output not preserved in log"; exit 1; }
parses "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: active.md no longer parses"; exit 1; }
echo "OK: failure path appends corrective with preserved output"

# (d) dedup on second run
before=$(grep -c "source: model-fleet:refresh-failure" "$BRAIN_PATH/tasks/active.md")
export MOCK_PROBE_FAIL=1
brain-model-fleet --apply >/dev/null 2>&1 || true
unset MOCK_PROBE_FAIL
after=$(grep -c "source: model-fleet:refresh-failure" "$BRAIN_PATH/tasks/active.md")
[ "$before" -eq "$after" ] && [ "$after" -eq 1 ] || { echo "FAILED: dedup ($before -> $after)"; exit 1; }
echo "OK: dedup"

# (e) brain-lint flags a missing registry, silence after --apply
rm -f "$registry"
run_lint() { PYTHONPATH="$PROJECT_ROOT/runtime/lib" python3 "$PROJECT_ROOT/runtime/bin/brain-lint" --brain "$BRAIN_PATH" --quiet 2>&1 || true; }
run_lint | grep -q "model fleet registry missing" || { echo "FAILED: lint misses missing registry"; exit 1; }
brain-model-fleet --apply >/dev/null 2>&1
run_lint | grep -q "model fleet registry missing" && { echo "FAILED: lint still warns after apply"; exit 1; }
echo "OK: lint guards registry freshness"