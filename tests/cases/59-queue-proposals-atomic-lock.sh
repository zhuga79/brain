#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying atomic + locked proposals.json writes"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
export PYTHONPATH="$PROJECT_ROOT/runtime/lib"

# Both producers must go through the shared lock helper. Логика queue-cycle
# живёт в brain_app.cycles.queue, CLI — фасад над ней, поэтому проверяем модуль.
grep -q "brain_launch_queue.lock" "$PROJECT_ROOT/runtime/bin/brain-dashboard" \
  || { echo "FAILED: brain-dashboard does not lock proposals writes"; exit 1; }
grep -q "brain_launch_queue.lock" "$PROJECT_ROOT/runtime/lib/brain_app/cycles/queue.py" \
  || { echo "FAILED: brain-queue-cycle does not lock proposals writes"; exit 1; }

# Lost-update test: 40 concurrent locked increments must all land (==40).
python3 -c "import sys,json;from pathlib import Path;import brain_launch_queue as q;q.atomic_write_json(q.proposals_path(Path(sys.argv[1])),{'n':0})" "$BRAIN_PATH"
for _ in $(seq 1 40); do
  python3 - "$BRAIN_PATH" <<'PY' &
import sys, json, time
from pathlib import Path
import brain_launch_queue as q
brain = Path(sys.argv[1]); path = q.proposals_path(brain)
with q.lock(brain):
    d = json.loads(path.read_text(encoding="utf-8"))
    n = int(d.get("n", 0))
    time.sleep(0.004)  # widen the race window inside the critical section
    d["n"] = n + 1
    q.atomic_write_json(path, d)
PY
done
wait

final=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['n'])" "$BRAIN_PATH/.brain/launch-queue/proposals.json")
[ "$final" = "40" ] || { echo "FAILED: lock did not prevent lost updates (final=$final, expected 40)"; exit 1; }
echo "lock serializes concurrent writes (no lost updates) OK"

# Lock file is created in the queue directory.
[ -f "$BRAIN_PATH/.brain/launch-queue/.proposals.lock" ] || { echo "FAILED: lock file missing"; exit 1; }

# No leftover temp files from atomic writes.
leftovers=$(find "$BRAIN_PATH/.brain/launch-queue" -name '.proposals.*.tmp' | wc -l)
[ "$leftovers" = "0" ] || { echo "FAILED: atomic-write temp files left behind ($leftovers)"; exit 1; }
echo "atomic write leaves no temp files OK"

echo ">>> queue-proposals atomic+lock checks passed"
