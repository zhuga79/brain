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

# ── 2. BRAIN_TEST_SANDBOX выставлен вручную, файла-маркера нет — отказ ──
# Раньше единственным признаком было расположение пути: любой каталог под
# /tmp плюс протёкшая переменная проходили guard. 2026-08-16 так были
# приняты за песочницу боевые git worktree в /tmp/wt-federation и
# /tmp/wt-cwd. Маркер нельзя унаследовать по ошибке — его создаёт только
# настоящий mktemp -d конкретно этого прогона.
set +e
out="$(env -u BRAIN_TEST_SANDBOX_MARKER BRAIN_TEST_SANDBOX=1 BRAIN_PATH="$PROJECT_ROOT" bash "$victim" 2>&1)"
rc=$?
set -e

[ "$rc" -ne 0 ] || { echo "FAILED: case ran against the live BRAIN_PATH without a marker file"; exit 1; }
grep -q "файл-маркер" <<< "$out" || {
    echo "FAILED: wrong refusal reason, got:"
    echo "$out" | head -5
    exit 1
}
echo "OK: refuses when there is no sandbox marker file"

# ── 2b. Живой чекаут под /tmp защищён так же, как под \$HOME ──
# Ровно форма аварии 2026-08-16: дерево лежит под /tmp, маркер настоящего
# прогона унаследован из окружения раннера — по старому правилу «префикс
# /tmp» этого хватало, чтобы пустить bootstrap внутрь. Теперь маркер
# привязан к своему каталогу, а это дерево ему не принадлежит.
fake_live="$(mktemp -d)"
set +e
out="$(BRAIN_TEST_SANDBOX=1 BRAIN_PATH="$fake_live" bash "$victim" 2>&1)"
rc=$?
set -e
rm -rf "$fake_live"

[ "$rc" -ne 0 ] || { echo "FAILED: case ran with BRAIN_PATH under /tmp outside the runner sandbox"; exit 1; }
grep -q "вне каталога песочницы" <<< "$out" || {
    echo "FAILED: wrong refusal reason, got:"
    echo "$out" | head -5
    exit 1
}
echo "OK: a foreign checkout under /tmp is refused too"

# ── 2c. Маркер честный, но для ДРУГОГО каталога, а BRAIN_PATH — боевой ──
# Это и есть форма реальной аварии: маркер существует (создан настоящим
# раннером для его собственной песочницы), но BRAIN_PATH указывает не на
# неё, а на боевое дерево — например потому что worktree совпал по префиксу
# пути. Самосогласованность маркера с BRAIN_PATH обязана провалиться.
marker_tmp="$(mktemp -d)"
marker_file="$marker_tmp/.brain-test-sandbox-marker"
printf '%s' "$(CDPATH= cd -- "$marker_tmp" && pwd -P)" > "$marker_file"

set +e
out="$(BRAIN_TEST_SANDBOX=1 BRAIN_TEST_SANDBOX_MARKER="$marker_file" BRAIN_PATH="$PROJECT_ROOT" bash "$victim" 2>&1)"
rc=$?
set -e
rm -rf "$marker_tmp"

[ "$rc" -ne 0 ] || { echo "FAILED: case ran against the live BRAIN_PATH with a foreign marker"; exit 1; }
grep -q "вне каталога песочницы" <<< "$out" || {
    echo "FAILED: wrong refusal reason, got:"
    echo "$out" | head -5
    exit 1
}
echo "OK: refuses when BRAIN_PATH points at live data outside the marker's sandbox"

# ── 2d. Маркер с подделанным содержимым — отказ ──
# Содержимое маркера обязано совпадать с каноническим путём его собственного
# каталога. Файл, созданный вручную (а не настоящим mktemp -d раннера),
# такой самосогласованности не даёт.
forged_tmp="$(mktemp -d)"
forged_marker="$forged_tmp/.brain-test-sandbox-marker"
printf 'not-a-real-path' > "$forged_marker"

set +e
out="$(BRAIN_TEST_SANDBOX=1 BRAIN_TEST_SANDBOX_MARKER="$forged_marker" BRAIN_PATH="$forged_tmp/brain" bash "$victim" 2>&1)"
rc=$?
set -e
rm -rf "$forged_tmp"

[ "$rc" -ne 0 ] || { echo "FAILED: case ran with a forged marker file"; exit 1; }
grep -q "не самосогласован" <<< "$out" || {
    echo "FAILED: wrong refusal reason, got:"
    echo "$out" | head -5
    exit 1
}
echo "OK: refuses a forged/tampered marker file"

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
