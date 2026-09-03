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
# BRAIN_SMOKE_CASES_DIR overrides the case directory — only the timeout
# self-test (99-runner-case-timeout) uses it, to run throwaway stub cases
# through a nested runner without touching tests/cases/.
CASES_DIR="${BRAIN_SMOKE_CASES_DIR:-$SCRIPT_DIR/cases}"

# Per-case wall-clock ceiling. A hung case — e.g. a watch loop waiting on a
# task completion that never comes (t-2026-09-01-smoke-per-case-timeout-context,
# where 14-e2e-launch-live spun ~10 min after brain-task complete started
# failing) — otherwise stalls the whole suite and keeps the run lock held.
# `timeout` in its default (non-foreground) mode signals the case's whole
# process group, so a `brain-dashboard serve` the case backgrounded is torn
# down with it instead of leaking past the suite.
CASE_TIMEOUT="${BRAIN_SMOKE_CASE_TIMEOUT:-180}"
CASE_KILL_GRACE="${BRAIN_SMOKE_CASE_KILL_GRACE:-10}"

# Second line of defence for hook isolation: drop every GIT_* by prefix.
# A named denylist leaks new git variables into nested git-using cases.
. "$SCRIPT_DIR/lib/drop-git-env.sh"

PATTERN="${1:-}"
TOTAL_START=$(date +%s%N)
PASSED=0
FAILED=0
SKIPPED=0
TOTAL=0

# Взаимоисключение прогонов раннера — общесистемное, не по дереву.
#
# Порты изолированы через pick_free_port (см. tests/_lib.sh), но кейсы также
# используют больше сотни фиксированных путей вида /tmp/brain_*.json,
# /tmp/brain_*.log и т.п. — не под $TMP_HOME, а прямо под /tmp по имени.
# Их пишут и тут же читают синхронно внутри одного кейса, поэтому для
# одиночного прогона это безобидно, но при двух ОДНОВРЕМЕННЫХ прогонах
# tests/run.sh (в том числе из разных деревьев — путь общий для любого
# чекаута) один и тот же файл перезаписывается конкурентно, и второй кейс
# читает чужие данные молча, без ошибки открытия файла. Изолировать
# каждый такой путь по дереву — бесконечная и растущая цель (новые кейсы
# продолжают заводить такие пути тем же способом); вместо этого раннер
# допускает только один активный прогон в системе и явно отказывает
# второму, а не тонет в скрытых гонках по /tmp.
#
# flock — ядерный advisory-лок: если процесс-держатель упадёт (даже kill -9),
# лок освобождается сам, без TTL и протухания в отличие от brain-lock.
# Путь фиксирован под /tmp, а не под TMPDIR: кейсы пишут /tmp/brain_*
# литералами, и два прогона с разным TMPDIR всё равно делят эти файлы
# (t-2026-08-16-smoke-suite-cannot-run-concurr). BRAIN_SMOKE_RUN_LOCK —
# только для точечной проверки самого лока, не для обхода сериализации.
if ! command -v flock >/dev/null 2>&1; then
    echo "ОТКАЗ: нет flock(1) — параллельный прогон tests/run.sh нельзя исключить." >&2
    echo "Смоук-кейсы делят фиксированные пути /tmp/brain_*.{json,log,out,err,txt,html}." >&2
    exit 3
fi
RUN_LOCK_FILE="${BRAIN_SMOKE_RUN_LOCK:-/tmp/brain-smoke-run.lock}"
# >> не режет файл: `exec 9>` до flock уничтожил бы pid держателя, и отказ
# не смог бы его напечатать.
exec 9>>"$RUN_LOCK_FILE"
if ! flock -n 9; then
    holder="$(tr -d '\0' < "$RUN_LOCK_FILE" 2>/dev/null || true)"
    echo "ОТКАЗ: другой прогон tests/run.sh уже активен (лок: $RUN_LOCK_FILE)." >&2
    [ -n "$holder" ] && echo "Держит: $holder" >&2
    echo "Смоук-кейсы делят фиксированные пути /tmp/brain_*.{json,log,out,err,txt,html}" >&2
    echo "между любыми деревьями — параллельный прогон портит данные соседа." >&2
    echo "Дождитесь завершения другого прогона (или его аварийного конца — лок" >&2
    echo "снимается автоматически) и повторите." >&2
    exit 3
fi
printf 'pid=%s started=%s\n' "$$" "$(date -Iseconds)" > "$RUN_LOCK_FILE"

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

# BRAIN_SMOKE_SKIP_BOOTSTRAP: skip the one-time setup + source verification.
# Only the timeout self-test (99-runner-case-timeout) sets it, to keep its
# nested runner fast; a real run always bootstraps.
if [ -n "${BRAIN_SMOKE_SKIP_BOOTSTRAP:-}" ]; then
    echo ">>> [bootstrap] skipped (BRAIN_SMOKE_SKIP_BOOTSTRAP)"
else
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
fi

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

    # exec 9>&- : кейс и его фоновые серверы не наследуют fd лока.
    # Иначе переживший suite `brain-dashboard serve` держал бы flock после
    # выхода раннера — второй прогон отказывал бы в пустоту.
    case_rc=0
    (export PROJECT_ROOT HOME BRAIN_PATH PATH; exec 9>&-; \
     exec timeout -k "$CASE_KILL_GRACE" "$CASE_TIMEOUT" bash "$case_file" 2>&1) || case_rc=$?
    case_end=$(date +%s%N)
    elapsed_ms=$(( (case_end - case_start) / 1000000 ))
    if [ "$case_rc" -eq 0 ]; then
        echo ">>> [case: $case_name] PASSED (${elapsed_ms}ms)"
        PASSED=$((PASSED + 1))
    elif [ "$case_rc" -eq 124 ] || [ "$case_rc" -eq 137 ]; then
        # 124: timeout sent SIGTERM. 137: -k had to follow up with SIGKILL.
        echo ">>> [case: $case_name] FAILED (timeout ${CASE_TIMEOUT}s)"
        FAILED=$((FAILED + 1))
    else
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
