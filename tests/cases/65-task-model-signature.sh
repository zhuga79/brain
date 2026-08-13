#!/usr/bin/env bash
# Test: every closed task is signed with the real model+version.
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying mandatory model signature on task completion"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki"
cat > "$BRAIN_PATH/tasks/active.md" <<'TASKS'
# Active Tasks

- [ ] [P1] t-2026-05-29-sig-flag — Signed via flag
      role: developer   mode: solo
      acceptance: ok

- [ ] [P1] t-2026-05-29-sig-env — Signed via env
      role: developer   mode: solo
      acceptance: ok

- [ ] [P1] t-2026-05-29-sig-none — Unsigned path
      role: developer   mode: solo
      acceptance: ok
TASKS
printf '# Done Tasks\n' > "$BRAIN_PATH/tasks/done.md"
printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"
( cd "$BRAIN_PATH" && git init -q && git add -A && git -c user.email=t@t -c user.name=t commit -qm init )

# 1. Signature via --model is recorded.
brain-task complete t-2026-05-29-sig-flag --as agent-x --model gemini-2.5-pro >/dev/null 2>&1
grep -A4 "t-2026-05-29-sig-flag" "$BRAIN_PATH/tasks/done.md" | grep -q "model: gemini-2.5-pro" \
  || { echo "FAILED: --model signature not recorded"; exit 1; }
echo "OK: --model signature recorded"

# 2. Signature falls back to BRAIN_AGENT_MODEL env.
BRAIN_AGENT_MODEL="claude-opus-4-8" brain-task complete t-2026-05-29-sig-env --as agent-y >/dev/null 2>&1
grep -A4 "t-2026-05-29-sig-env" "$BRAIN_PATH/tasks/done.md" | grep -q "model: claude-opus-4-8" \
  || { echo "FAILED: BRAIN_AGENT_MODEL signature not recorded"; exit 1; }
echo "OK: env signature recorded"

# 3. Missing signature warns and records 'unsigned' (non-strict default).
out=$(brain-task complete t-2026-05-29-sig-none --as agent-z 2>&1 || true)
grep -q "WARN: closing" <<< "$out" || { echo "FAILED: no WARN on missing signature"; exit 1; }
grep -A4 "t-2026-05-29-sig-none" "$BRAIN_PATH/tasks/done.md" | grep -q "model: unsigned" \
  || { echo "FAILED: unsigned marker not recorded"; exit 1; }
echo "OK: missing signature warns + records 'unsigned'"

# 4. Strict mode (BRAIN_REQUIRE_MODEL=1) refuses to close without a signature.
cat >> "$BRAIN_PATH/tasks/active.md" <<'T2'

- [ ] [P1] t-2026-05-29-sig-strict — Strict mode
      role: developer   mode: solo
      acceptance: ok
T2
if BRAIN_REQUIRE_MODEL=1 brain-task complete t-2026-05-29-sig-strict --as agent-w >/dev/null 2>&1; then
  echo "FAILED: strict mode should refuse unsigned completion"; exit 1
fi
grep -q "t-2026-05-29-sig-strict" "$BRAIN_PATH/tasks/active.md" \
  || { echo "FAILED: strict-refused task should stay active"; exit 1; }
echo "OK: strict mode refuses unsigned completion"

echo ">>> task model signature checks passed"
