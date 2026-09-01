#!/usr/bin/env bash
# tests/run.sh — Pattern-based test runner for Brain smoke cases
#
# Usage:
#   bash tests/run.sh              # run all cases
#   bash tests/run.sh phase6       # run cases matching "phase6"
#   bash tests/run.sh webhook      # run cases matching "webhook"
#   bash tests/run.sh dashboard    # run cases matching "dashboard"
#
# Each case file in tests/cases/ is an executable bash script that:
#   1. sources tests/_lib.sh for shared helpers
#   2. runs its isolated tests
#   3. exits 0 on success, non-zero on failure
#
# The runner tracks total runtime and reports per-case timing.

set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
CASES_DIR="$SCRIPT_DIR/cases"

# Second line of defence for hook isolation: drop every GIT_* by prefix.
# A named denylist leaks new git variables into nested git-using cases.
. "$SCRIPT_DIR/lib/drop-git-env.sh"

PATTERN="${1:-}"
TOTAL_START=$(date +%s%N)
PASSED=0
FAILED=0
SKIPPED=0
TOTAL=0

echo ">>> Running Brain smoke test runner (pattern: ${PATTERN:-all})"
echo ">>> Project root: $PROJECT_ROOT"

# Set up the main brain once for all cases (like the original smoke.sh)
TMP_HOME=$(mktemp -d)
export HOME="$TMP_HOME"
export BRAIN_PATH="$HOME/brain"
export PATH="$HOME/.local/bin:$PATH"
# Песочница задаёт корни целиком, а не поверх шелла оператора. С унаследованным
# BRAIN_SYSTEM_PATH setup-brain-v2.sh считает установку разделённой и не создаёт
# $BRAIN/roles — бутстрап падал на первом же legacy-скрипте. BRAIN_ENV_FILE
# увёл бы корни в файл оператора уже после подмены HOME.
unset BRAIN_SYSTEM_PATH BRAIN_ENV_FILE
# Признак песочницы для tests/lib/sandbox-guard.sh: кейс, запущенный в обход
# раннера, увидит его отсутствие и откажется работать по боевым данным.
export BRAIN_TEST_SANDBOX=1
# Файл-маркер, самосогласованный со своим каталогом: содержит канонический
# путь каталога, в котором лежит. Guard проверяет и совпадение содержимого,
# и то, что BRAIN_PATH — потомок этого каталога, а не просто "что-то под
# /tmp" (см. tests/lib/sandbox-guard.sh — расположение пути само по себе не
# доказывает, что дерево ephemeral).
BRAIN_TEST_SANDBOX_MARKER="$TMP_HOME/.brain-test-sandbox-marker"
printf '%s' "$(CDPATH= cd -- "$TMP_HOME" && pwd -P)" > "$BRAIN_TEST_SANDBOX_MARKER"
export BRAIN_TEST_SANDBOX_MARKER

# Состав провайдерских CLI задаёт песочница, а не хост. Каталог заглушек идёт
# первым в PATH и перекрывает настоящие codex/gemini/claude/opencode: без
# этого решение маршрутизатора зависело от того, что установлено на машине, и
# смоук показывал 100/100 у оператора против 92/100 на чистом раннере.
# Подробности — в tests/lib/provider-stubs.sh.
. "$SCRIPT_DIR/lib/provider-stubs.sh"
STUB_BIN=$(make_provider_stubs "$TMP_HOME/.provider-stubs")
export PATH="$STUB_BIN:$PATH"

echo ">>> [bootstrap] Running setup scripts"
scripts=(
    setup-brain-v2.sh
    add-teams-brain.sh
    add-pm-finance-brain.sh
    add-design-negotiator-brain.sh
    refine-tax-boundaries.sh
    add-power-features-brain.sh
    patch-brain-run-doctrine.sh
)
for s in "${scripts[@]}"; do
    bash "$PROJECT_ROOT/$s" > /dev/null
done

# Verify binaries once
echo ">>> Verifying executability for runtime/bin"
for s in "$PROJECT_ROOT"/runtime/bin/*; do
    [ -f "$s" ] || continue
    [ -x "$s" ] || { echo "FAILED: $s is not executable"; exit 1; }
done

echo ">>> Verifying bash -n for all scripts"
for s in "$PROJECT_ROOT"/*.sh; do
    bash -n "$s"
done
for s in "$PROJECT_ROOT"/runtime/bin/*; do
    [ -f "$s" ] || continue
    first_line=$(head -n 1 "$s")
    if echo "$first_line" | grep -Eq 'bash|sh'; then
        bash -n "$s"
    elif echo "$first_line" | grep -q 'python'; then
        python3 -c "from pathlib import Path; import sys; p = Path(sys.argv[1]); compile(p.read_text(), str(p), 'exec')" "$s"
    fi
done
# brain_wiki is now a package — syntax-check each submodule
for _bw_mod in brain_wiki/__init__.py brain_wiki/frontmatter.py brain_wiki/pages.py brain_wiki/validators.py brain_wiki/writers.py; do
    python3 -c "from pathlib import Path; import sys; p = Path(sys.argv[1]); compile(p.read_text(), str(p), 'exec')" "$PROJECT_ROOT/runtime/lib/$_bw_mod"
done
python3 -c "from pathlib import Path; import sys; p = Path(sys.argv[1]); compile(p.read_text(), str(p), 'exec')" "$PROJECT_ROOT/runtime/lib/brain_index.py"
python3 -c "from pathlib import Path; import sys; p = Path(sys.argv[1]); compile(p.read_text(), str(p), 'exec')" "$PROJECT_ROOT/runtime/mcp/server.py"
grep -q "from tools_prd import" "$PROJECT_ROOT/runtime/mcp/server.py"
grep -q "@mcp.tool()" "$PROJECT_ROOT/runtime/mcp/tools_prd.py"
grep -q "def init_prd" "$PROJECT_ROOT/runtime/mcp/tools_prd.py"
grep -q "def commit_prd" "$PROJECT_ROOT/runtime/mcp/tools_prd.py"

# Run case files
for case_file in "$CASES_DIR"/*.sh; do
    [ -f "$case_file" ] || continue
    case_name=$(basename "$case_file" .sh)

    # Apply pattern filter
    if [ -n "$PATTERN" ] && ! echo "$case_name" | grep -q "$PATTERN"; then
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    TOTAL=$((TOTAL + 1))
    case_start=$(date +%s%N)
    echo ""
    echo ">>> [case: $case_name] Starting"

    if (export PROJECT_ROOT HOME BRAIN_PATH PATH; bash "$case_file" 2>&1); then
        case_end=$(date +%s%N)
        elapsed_ms=$(( (case_end - case_start) / 1000000 ))
        echo ">>> [case: $case_name] PASSED (${elapsed_ms}ms)"
        PASSED=$((PASSED + 1))
    else
        case_end=$(date +%s%N)
        elapsed_ms=$(( (case_end - case_start) / 1000000 ))
        echo ">>> [case: $case_name] FAILED (${elapsed_ms}ms)"
        FAILED=$((FAILED + 1))
    fi
done

# Cleanup
rm -rf "$TMP_HOME"

# Summary
total_end=$(date +%s%N)
total_ms=$(( (total_end - TOTAL_START) / 1000000 ))
echo ""
echo "=========================================="
echo "  Results: $PASSED passed, $FAILED failed, $SKIPPED skipped (of $TOTAL run)"
echo "  Total time: ${total_ms}ms"
echo "=========================================="

if [ "$FAILED" -gt 0 ]; then
    echo "FAILED"
    exit 1
fi

echo ">>> ALL TESTS PASSED"
