#!/usr/bin/env bash
# case: sandbox-guard — кейс, запущенный в обход раннера, обязан отказаться
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying test cases refuse to run outside the sandbox"

victim="$PROJECT_ROOT/tests/cases/02-bootstrap.sh"
[ -f "$victim" ] || { echo "FAILED: no case to probe"; exit 1; }

# Снимок состояния до пробы. Сравниваем «до и после», а не требуем чистого
# дерева: параллельно с тестами может идти агент, и его правки в handoff/
# к этой проверке отношения не имеют.
before_state="$(cd "$PROJECT_ROOT" && git status --porcelain tasks/ handoff/ 2>/dev/null || true)"

# ── 1. Без маркера песочницы кейс не должен даже начать работу ──
# env -u снимает переменные, которые кейс унаследовал бы от раннера.
set +e
out="$(env -u BRAIN_TEST_SANDBOX -u BRAIN_PATH bash "$victim" 2>&1)"
rc=$?
set -e

[ "$rc" -ne 0 ] || { echo "FAILED: case ran without the sandbox marker"; exit 1; }
grep -q "ОТКАЗ" <<< "$out" || {
    echo "FAILED: no refusal message, got:"
    echo "$out" | head -5
    exit 1
}
echo "OK: refuses without the sandbox marker"

# ── 2. Маркер выставлен вручную, но BRAIN_PATH боевой — тоже отказ ──
# Иначе защиту снимал бы один export, а промах с путём и есть та ошибка,
# от которой guard защищает.
set +e
out="$(BRAIN_TEST_SANDBOX=1 BRAIN_PATH="$PROJECT_ROOT" bash "$victim" 2>&1)"
rc=$?
set -e

[ "$rc" -ne 0 ] || { echo "FAILED: case ran against the live BRAIN_PATH"; exit 1; }
grep -q "вне временного каталога" <<< "$out" || {
    echo "FAILED: wrong refusal reason, got:"
    echo "$out" | head -5
    exit 1
}
echo "OK: refuses when BRAIN_PATH points at live data"

# ── 3. Боевые данные не пострадали ──
# Главное, ради чего guard существует: 2026-08-10 прямой запуск кейсов стёр
# очередь задач и handoff/, а brain-task разнёс это по git автокоммитами.
after_state="$(cd "$PROJECT_ROOT" && git status --porcelain tasks/ handoff/ 2>/dev/null || true)"
[ "$before_state" = "$after_state" ] || {
    echo "FAILED: live data changed while probing the guard:"
    diff <(echo "$before_state") <(echo "$after_state") || true
    exit 1
}
echo "OK: live tasks/ and handoff/ untouched"

# ── 4. Guard подключён ко всем кейсам ──
# Через tests/_lib.sh, который подключают все кейсы: так защита достаётся и
# тем, что появятся позже.
grep -q "sandbox-guard.sh" "$PROJECT_ROOT/tests/_lib.sh" || {
    echo "FAILED: tests/_lib.sh no longer sources the guard"
    exit 1
}
missing=0
for case_file in "$PROJECT_ROOT"/tests/cases/*.sh; do
    grep -q "_lib.sh" "$case_file" || {
        echo "FAILED: case without the guard: $(basename "$case_file")"
        missing=1
    }
done
[ "$missing" -eq 0 ] || exit 1
echo "OK: every case is covered by the guard"
