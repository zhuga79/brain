#!/usr/bin/env bash
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-task complete recovers from crash between done and active"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki"

cat > "$BRAIN_PATH/tasks/active.md" <<'EOF'
# Active Tasks

- [~] [P1] t-recover-smoke — Recoverable smoke task
      role: developer   mode: solo
      acceptance: ok
      started: 2026-08-14T00:00:00Z
      by: smoke-agent
EOF
printf '# Done Tasks\n' > "$BRAIN_PATH/tasks/done.md"
printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"

python3 - "$BRAIN_PATH/tasks/active.md" "$BRAIN_PATH/tasks/done.md" <<'PY'
import sys
from pathlib import Path

from brain_core import taskfile

active = Path(sys.argv[1])
done = Path(sys.argv[2])
real_write = taskfile.atomic_write
tripped = False

def flaky_write(path: Path, text: str) -> None:
    global tripped
    real_write(path, text)
    if path == done and not tripped:
        tripped = True
        raise RuntimeError("boom-after-done")

taskfile.atomic_write = flaky_write
try:
    taskfile.complete(active, done, "t-recover-smoke", "smoke-agent", "openai-gpt-5.4")
except RuntimeError as exc:
    if str(exc) != "boom-after-done":
        raise
else:
    raise SystemExit("expected injected crash")
PY

grep -q 't-recover-smoke —' "$BRAIN_PATH/tasks/active.md" || {
  echo "FAILED: task disappeared from active.md after injected crash"
  exit 1
}
[ "$(grep -c -- '- \[x\].*t-recover-smoke —' "$BRAIN_PATH/tasks/done.md" || true)" -eq 1 ] || {
  echo "FAILED: expected one done entry after injected crash"
  cat "$BRAIN_PATH/tasks/done.md"
  exit 1
}
[ -f "$BRAIN_PATH/tasks/.taskfile-complete/t-recover-smoke.json" ] || {
  echo "FAILED: recovery journal missing after injected crash"
  exit 1
}

brain-task complete t-recover-smoke --as smoke-agent --model openai-gpt-5.4 >/dev/null

if grep -q 't-recover-smoke —' "$BRAIN_PATH/tasks/active.md"; then
  echo "FAILED: task still present in active.md after retry"
  exit 1
fi
[ "$(grep -c -- '- \[x\].*t-recover-smoke —' "$BRAIN_PATH/tasks/done.md" || true)" -eq 1 ] || {
  echo "FAILED: retry duplicated done entry"
  cat "$BRAIN_PATH/tasks/done.md"
  exit 1
}
[ ! -e "$BRAIN_PATH/tasks/.taskfile-complete/t-recover-smoke.json" ] || {
  echo "FAILED: recovery journal was not cleaned"
  exit 1
}

echo ">>> taskfile complete recovery checks passed"
