#!/usr/bin/env bash
# Test: every closed task is signed with a versioned model; unsigned is opt-in.
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

# 3. Missing signature is refused by default (no silent unsigned).
out=$(brain-task complete t-2026-05-29-sig-none --as agent-z 2>&1 || true)
grep -qi "model signature required" <<< "$out" || { echo "FAILED: no error on missing signature: $out"; exit 1; }
grep -q "t-2026-05-29-sig-none" "$BRAIN_PATH/tasks/active.md" \
  || { echo "FAILED: unsigned-by-default should have left the task active"; exit 1; }
grep -q "t-2026-05-29-sig-none" "$BRAIN_PATH/tasks/done.md" \
  && { echo "FAILED: missing signature closed the task"; exit 1; }
echo "OK: missing signature refuses to close"

# 4. BRAIN_REQUIRE_MODEL is no longer the switch: default is already strict.
cat >> "$BRAIN_PATH/tasks/active.md" <<'T2'

- [ ] [P1] t-2026-05-29-sig-strict — Strict mode
      role: developer   mode: solo
      acceptance: ok
T2
if BRAIN_REQUIRE_MODEL=0 brain-task complete t-2026-05-29-sig-strict --as agent-w >/dev/null 2>&1; then
  echo "FAILED: BRAIN_REQUIRE_MODEL=0 must not restore silent unsigned"; exit 1
fi
grep -q "t-2026-05-29-sig-strict" "$BRAIN_PATH/tasks/active.md" \
  || { echo "FAILED: REQUIRE_MODEL=0 should still leave the task active"; exit 1; }
echo "OK: BRAIN_REQUIRE_MODEL=0 is not an unsigned hatch"

# 5. Explicit hatch records unsigned and audits it.
cat >> "$BRAIN_PATH/tasks/active.md" <<'T3'

- [ ] [P1] t-2026-05-29-sig-hatch — Explicit unsigned hatch
      role: developer   mode: solo
      acceptance: ok
T3
out=$(brain-task complete t-2026-05-29-sig-hatch --as agent-h --allow-unsigned 2>&1) \
  || { echo "FAILED: --allow-unsigned complete failed: $out"; exit 1; }
grep -A4 "t-2026-05-29-sig-hatch" "$BRAIN_PATH/tasks/done.md" | grep -q "model: unsigned" \
  || { echo "FAILED: hatch did not record model: unsigned"; exit 1; }
grep -q "model-unsigned" "$BRAIN_PATH/wiki/log.md" \
  || { echo "FAILED: unsigned hatch was not audited"; exit 1; }
echo "OK: --allow-unsigned records unsigned and audits"

# 6. Env hatch is also explicit and audited.
cat >> "$BRAIN_PATH/tasks/active.md" <<'T4'

- [ ] [P1] t-2026-05-29-sig-env-hatch — Env unsigned hatch
      role: developer   mode: solo
      acceptance: ok
T4
out=$(BRAIN_ALLOW_UNSIGNED_MODEL=1 brain-task complete t-2026-05-29-sig-env-hatch --as agent-e 2>&1) \
  || { echo "FAILED: env hatch complete failed: $out"; exit 1; }
grep -A4 "t-2026-05-29-sig-env-hatch" "$BRAIN_PATH/tasks/done.md" | grep -q "model: unsigned" \
  || { echo "FAILED: env hatch did not record model: unsigned"; exit 1; }
echo "OK: BRAIN_ALLOW_UNSIGNED_MODEL records unsigned"

echo ">>> task model signature checks passed"
