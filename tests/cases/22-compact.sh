#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-compact stdin compactors and artifacts"
raw_artifact="$BRAIN_PATH/.brain/artifacts/compact-smoke.log"
python3 - <<'PYEOF' | brain-compact --kind rg --limit-lines 20 --raw-artifact "$raw_artifact" > /tmp/brain_compact_rg.txt
for i in range(35):
    print(f"runtime/lib/file{i % 3}.py:{i}: repeated match line {i}")
print("runtime/lib/file0.py:99: ERROR exact failure survives")
PYEOF
grep -q "runtime/lib/file0.py" /tmp/brain_compact_rg.txt || { echo "FAILED: rg compact missing grouped file"; exit 1; }
grep -q "ERROR exact failure survives" /tmp/brain_compact_rg.txt || { echo "FAILED: rg compact missing important line"; exit 1; }
grep -q "\[raw artifact\]" /tmp/brain_compact_rg.txt || { echo "FAILED: rg compact missing raw artifact marker"; exit 1; }
[ -f "$raw_artifact" ] || { echo "FAILED: raw artifact not created"; exit 1; }

echo ">>> Verifying brain-compact JSON metrics"
printf "one\ntwo\ntwo\nFAILED keep me\n" | brain-compact --kind test --json > /tmp/brain_compact_metrics.json
python3 - <<'PYEOF'
import json
from pathlib import Path
data = json.loads(Path("/tmp/brain_compact_metrics.json").read_text())
assert data["kind"] == "test", data
assert data["raw_bytes"] > 0, data
assert data["compact_bytes"] > 0, data
assert "FAILED keep me" in data["output"], data
assert "raw_tokens_est" in data, data
assert "compact_tokens_est" in data, data
PYEOF

echo ">>> Verifying brain-compact command mode and exit code"
set +e
brain-compact --kind test --raw-artifact "$BRAIN_PATH/.brain/artifacts/compact-fail.log" -- python3 -c 'import sys; print("FAILED command-mode"); sys.exit(7)' > /tmp/brain_compact_cmd.txt
cmd_exit=$?
set -e
[ "$cmd_exit" -eq 7 ] || { echo "FAILED: command exit code not preserved ($cmd_exit)"; exit 1; }
grep -q "FAILED command-mode" /tmp/brain_compact_cmd.txt || { echo "FAILED: command failure line not preserved"; exit 1; }

echo "brain-compact OK"
