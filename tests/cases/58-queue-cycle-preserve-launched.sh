#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying queue-cycle preserves launched proposals on daily apply"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki" "$BRAIN_PATH/roles" "$BRAIN_PATH/.brain/launch-queue"
cat > "$BRAIN_PATH/tasks/active.md" <<'TASKS'
# Active Tasks

- [ ] [P1] t-2026-05-29-launched-open — Already launched but still open
      role: developer   mode: solo
      acceptance: Stays launched, not re-emitted as pending.

- [ ] [P1] t-2026-05-29-fresh-ready — Fresh runnable task
      role: developer   mode: solo
      acceptance: Becomes a pending proposal.
TASKS
cat > "$BRAIN_PATH/tasks/done.md" <<'DONE'
# Done Tasks
DONE
cat > "$BRAIN_PATH/wiki/log.md" <<'LOG'
# Log
LOG
cat > "$BRAIN_PATH/wiki/index.md" <<'IDX'
# Wiki Index
IDX
cat > "$BRAIN_PATH/roles/developer.md" <<'ROLE'
# Developer
ROLE

# Pre-existing proposal file with a launched proposal for an open task.
cat > "$BRAIN_PATH/.brain/launch-queue/proposals.json" <<'JSON'
{
  "ok": true,
  "generated_at": "2026-05-29T09:00:00Z",
  "summary": {"pending": 0},
  "proposals": [
    {
      "id": "qp-2026-05-29-t-2026-05-29-launched-open",
      "status": "launched",
      "launched_at": "2026-05-29T09:05:00Z",
      "task": "t-2026-05-29-launched-open",
      "title": "Already launched but still open",
      "role": "developer",
      "client": "codex",
      "workspace": ""
    }
  ]
}
JSON

brain-queue-cycle --brain "$BRAIN_PATH" --apply --json > "$BRAIN_FACTORY_TMP/queue-cycle.json"

python3 - "$BRAIN_PATH/.brain/launch-queue/proposals.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
props = {p["task"]: p for p in data.get("proposals", [])}

launched = props.get("t-2026-05-29-launched-open")
assert launched is not None, f"launched proposal dropped: {data}"
assert launched["status"] == "launched", f"launched status not preserved: {launched}"
assert launched.get("launched_at") == "2026-05-29T09:05:00Z", f"launched_at lost: {launched}"

# The launched task must NOT also appear as a second pending proposal.
launched_entries = [p for p in data["proposals"] if p["task"] == "t-2026-05-29-launched-open"]
assert len(launched_entries) == 1, f"launched task re-emitted: {launched_entries}"

fresh = props.get("t-2026-05-29-fresh-ready")
assert fresh is not None and fresh["status"] == "pending", f"fresh task not pending: {fresh}"
print("queue-cycle preserves launched state and does not re-emit OK")
PY

echo ">>> queue-cycle preserve-launched checks passed"
