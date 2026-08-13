#!/usr/bin/env bash
# 41-prd-decompose-mock — smoke test for brain-prd decompose with mock LLM
set -euo pipefail

# Support both direct invocation and invocation via run.sh
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Setting up isolated brain factory for prd-decompose mock test"
brain_factory

BIN="$PROJECT_ROOT/runtime/bin"

# Create brain directory structure
mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/prd" "$BRAIN_PATH/wiki" \
         "$BRAIN_PATH/council" "$BRAIN_PATH/teams" "$BRAIN_PATH/.locks"
touch "$BRAIN_PATH/wiki/log.md"

# Copy the PRD template
cp "$HOME/../brain/prd/_TEMPLATE.md" "$BRAIN_PATH/prd/" 2>/dev/null \
  || cp /home/user/brain/prd/_TEMPLATE.md "$BRAIN_PATH/prd/" 2>/dev/null \
  || cat > "$BRAIN_PATH/prd/_TEMPLATE.md" << 'TMPL_EOF'
---
status: draft
task: <task-id>
created: <ts>
---

# PRD: <Title>

## Context

## Goals

## Non-goals

## Subtasks
TMPL_EOF

# --- Create mock LLM provider FIRST so it's in PATH before brain-prd ---
MOCK_BIN="$BRAIN_FACTORY_TMP/mock-bin"
mkdir -p "$MOCK_BIN"
cat > "$MOCK_BIN/mock-llm" << 'MOCK_EOF'
#!/usr/bin/env bash
# mock-llm — echoes pre-recorded LLM output regardless of stdin/flags
cat << 'OUTPUT_EOF'
- [ ] [P1] s1-design — Define architecture
      role: architect
      mode: solo
      acceptance: ADR written

- [ ] [P1] s2-implement — Implement feature
      role: developer
      mode: solo
      acceptance: Feature works end-to-end

- [ ] [P2] s3-test — Write tests
      role: reviewer
      mode: solo
      acceptance: Coverage >= 80%
OUTPUT_EOF
MOCK_EOF
chmod +x "$MOCK_BIN/mock-llm"

# Set PATH with mock-llm FIRST, then brain bins
export PATH="$MOCK_BIN:$BIN:$PATH"

# --- Create a minimal active.md with a parent task ---
PARENT_ID="t-smoke-decompose-test"
cat > "$BRAIN_PATH/tasks/active.md" << 'ACTIVE_EOF'
# Active tasks

## P1

- [ ] [P1] t-smoke-decompose-test — Smoke decompose test task
      role: architect
      mode: prd
ACTIVE_EOF

# Add mock-llm to the provider matrix
cat > "$BRAIN_PATH/wiki/provider-matrix.json" << 'MATRIX_EOF'
{
  "version": 1,
  "updated": "2026-05-09",
  "source": "smoke-test",
  "roles": {
    "architect": [
      {"rank": 1, "provider": "mock-llm", "model": "mock", "command": "mock-llm", "use_for": "smoke test"}
    ]
  },
  "routes": {}
}
MATRIX_EOF

# --- Init PRD ---
brain-prd init "$PARENT_ID" >/dev/null 2>&1

# Check PRD file created
PRD_FILE="$BRAIN_PATH/prd/$PARENT_ID.md"
[ -f "$PRD_FILE" ] || fail_case "PRD file not created at $PRD_FILE"
echo ">>> PRD file created: OK"

# --- dry-run: must not write to active.md ---
ACTIVE_BEFORE=$(cat "$BRAIN_PATH/tasks/active.md")
DRY_OUTPUT=$(brain-prd decompose "$PARENT_ID" --llm mock-llm --dry-run 2>/dev/null)
ACTIVE_AFTER=$(cat "$BRAIN_PATH/tasks/active.md")

[ "$ACTIVE_BEFORE" = "$ACTIVE_AFTER" ] || fail_case "dry-run modified active.md"
echo ">>> --dry-run did not modify active.md: OK"

# dry-run output must contain task block markers or DRY-RUN indicator
echo "$DRY_OUTPUT" | grep -qiE "s1-design|s2-implement|s3-test|stub=True|DRY-RUN" \
  || fail_case "dry-run output missing expected content. Got: $DRY_OUTPUT"
echo ">>> --dry-run output contains task blocks: OK"

# dry-run output count: at least 3 subtask IDs
SUBTASK_COUNT=$(echo "$DRY_OUTPUT" | grep -c "s[0-9]-" || true)
[ "$SUBTASK_COUNT" -ge 3 ] || fail_case "expected >=3 subtask entries, got $SUBTASK_COUNT"
echo ">>> --dry-run output has $SUBTASK_COUNT subtask entries: OK"

# --- secret safety: env var secret must not leak into dry-run stdout ---
FAKE_SECRET="sk-smoke-TOPSECRET-99999"
export FAKE_SECRET_ENV="$FAKE_SECRET"
DRY_OUTPUT2=$(brain-prd decompose "$PARENT_ID" --llm mock-llm --dry-run 2>/dev/null)
if echo "$DRY_OUTPUT2" | grep -q "$FAKE_SECRET"; then
  fail_case "secret leaked into dry-run output"
fi
echo ">>> Secret not in dry-run output: OK"
unset FAKE_SECRET_ENV

echo ">>> 41-prd-decompose-mock: ALL CHECKS PASSED"
