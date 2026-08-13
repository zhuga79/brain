#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying Autonomous Skill Curator E2E cycle"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

# 1. Simulate a rate-limit error in logs
mkdir -p "$BRAIN_PATH/wiki"
echo "## [2026-05-13T12:00:00Z] orchestrator-handoff | t-mock | gemini-3-flash-test | limit-exhausted" > "$BRAIN_PATH/wiki/log.md"

# 2. Run monitor
brain-curator monitor >/dev/null
[ -f "$BRAIN_PATH/wiki/wishlist.json" ] || { echo "FAILED: wishlist.json not created"; exit 1; }
grep -q "gemini-3-flash-test hit rate limit" "$BRAIN_PATH/wiki/wishlist.json" || { echo "FAILED: monitor did not catch the limit error"; exit 1; }
echo "Curator Monitor OK"

# 3. Run search
brain-curator search >/dev/null
grep -q '"status": "synthesizing"' "$BRAIN_PATH/wiki/wishlist.json" || { echo "FAILED: search did not update status"; exit 1; }
echo "Curator Search OK"

# 4. Run synthesize
brain-curator synthesize >/dev/null
[ -d "$BRAIN_PATH/wiki/proposals" ] || { echo "FAILED: proposals directory not created"; exit 1; }
ls "$BRAIN_PATH/wiki/proposals"/*.md >/dev/null 2>&1 || { echo "FAILED: no proposal markdown created"; exit 1; }
echo "Curator Synthesis OK"

# 5. Run rank-models
brain-curator rank-models >/dev/null
[ -f "$BRAIN_PATH/wiki/model-fleet-report.md" ] || { echo "FAILED: model fleet report not created"; exit 1; }
echo "Curator Rank Models OK"

# 6. Run monitor-limits
brain-curator monitor-limits >/dev/null
[ -f "$BRAIN_PATH/.provider-health.json" ] || { echo "FAILED: .provider-health.json not created"; exit 1; }
grep -q "gemini-3-flash-test" "$BRAIN_PATH/.provider-health.json" || { echo "FAILED: health monitor missed the agent"; exit 1; }
echo "Curator Limit Monitor OK"

echo "Autonomous Curator E2E OK"
