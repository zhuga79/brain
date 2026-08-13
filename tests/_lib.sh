#!/usr/bin/env bash
# tests/_lib.sh — Shared helpers for Brain smoke test cases
#
# Usage: source this file from case scripts or run.sh.
# Provides: brain_factory, cleanup_all_tmpdirs, assert_*, and common env setup.

set -euo pipefail

# Отказ работать по боевым данным. Подключено здесь, а не в каждом кейсе:
# все 75 кейсов делают source этого файла, поэтому защита распространяется и
# на кейсы, которые появятся позже, — забыть её нельзя.
. "$(dirname "${BASH_SOURCE[0]}")/lib/sandbox-guard.sh"

# ── Globals (set by run.sh or smoke.sh entry point) ──
# PROJECT_ROOT: absolute path to project root
# CASES: array of case files to run
# PATTERN: optional filter (case file basename must contain this string)

ALL_TMPDIRS=()  # track all temp dirs for cleanup

# Библиотека ядра ставится пакетом (pip install -e / .pth в user site).
# Кейсы же запускают CLI прямо из дерева и подменяют HOME на временный, где
# никакой установки нет. Поэтому каталог библиотеки объявляет сама обвязка:
# это знание о расположении чекаута, а не bootstrap внутри каждого файла —
# именно от него мы и уходили в t-2026-08-10-core-packaging.
if [ -n "${PROJECT_ROOT:-}" ]; then
  # runtime/mcp тоже: при обычном запуске сервер стартует по пути, и Python
  # сам кладёт каталог скрипта в sys.path. Кейс же грузит server.py как
  # файл, поэтому каталог нужно назвать явно.
  export PYTHONPATH="$PROJECT_ROOT/runtime/lib:$PROJECT_ROOT/runtime/mcp${PYTHONPATH:+:$PYTHONPATH}"
fi


# ── Helpers ──

log_case() {
    echo ">>> [case: ${1:-unknown}] $2"
}

fail_case() {
    echo "FAILED: ${1:-unknown case failure}"
    exit 1
}

# Create an isolated brain factory with its own HOME/tmpdir.
# Sets HOME, BRAIN_PATH, PATH for the caller.
# Returns tmpdir path via BRAIN_FACTORY_TMP env var.
brain_factory() {
    local td
    td=$(mktemp -d)
    ALL_TMPDIRS+=("$td")
    export HOME="$td"
    export BRAIN_PATH="$td/brain"
    export PATH="$td/.local/bin:$PATH"
    export BRAIN_FACTORY_TMP="$td"
}

# Дождаться отвязанной перестройки индекса.
#
# Мутация очереди запускает `brain_core.rebuild &` и выходит — процесс
# переподчиняется init, `wait` его не видит и он продолжает писать в
# `.brain/index` уже после конца кейса. Уборка изредка падала на «Каталог не
# пуст»: rm обходил дерево, пока в него добавляли файлы. Ждём освобождения
# замка ребилда — это тот же замок, под которым работает сам ребилд.
wait_for_index_rebuild() {
    local brain="${1:-${BRAIN_PATH:-}}"
    [ -n "$brain" ] && [ -f "$brain/.brain/rebuild.lock" ] || return 0
    python3 - "$brain/.brain/rebuild.lock" <<'PY' 2>/dev/null || true
import fcntl, os, sys, time

path = sys.argv[1]
deadline = time.time() + 15
while time.time() < deadline:
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        break
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        break
    except OSError:
        time.sleep(0.1)
    finally:
        os.close(fd)
PY
}

# Cleanup all tracked tmpdirs.
cleanup_all_tmpdirs() {
    wait_for_index_rebuild
    for td in "${ALL_TMPDIRS[@]}"; do
        [ -d "$td" ] && rm -rf "$td"
    done
}

trap cleanup_all_tmpdirs EXIT

# ── Assertions ──

assert_executable() {
    [ -x "$1" ] || fail_case "not executable: $1"
}

assert_file_exists() {
    [ -f "$1" ] || fail_case "file missing: $1"
}

assert_contains() {
    local file="$1" pattern="$2"
    grep -q "$pattern" "$file" || fail_case "file '$file' missing pattern: $pattern"
}

assert_exit_nonzero() {
    set +e
    "$@" > /dev/null 2>&1
    local rc=$?
    set -e
    [ "$rc" -ne 0 ] || fail_case "expected non-zero exit: $*"
}

assert_exit_nonzero_with_msg() {
    local expected_msg="$1"; shift
    set +e
    local output
    output=$("$@" 2>&1); local rc=$?
    set -e
    [ "$rc" -ne 0 ] || fail_case "expected non-zero exit: $*"
    echo "$output" | grep -qi "$expected_msg" || fail_case "expected error message '$expected_msg' in: $output"
}

# ── Setup bootstrap (run setup scripts once per test session) ──

run_bootstrap_scripts() {
    local scripts=(
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
}

# ── Verify all binaries are executable and syntax-clean ──

verify_binaries() {
    echo ">>> Verifying executability for runtime/bin"
    for s in "$PROJECT_ROOT"/runtime/bin/*; do
        [ -f "$s" ] || continue
        assert_executable "$s"
    done

    echo ">>> Verifying bash -n for all scripts"
    for s in "$PROJECT_ROOT"/*.sh; do
        bash -n "$s"
    done
    for s in "$PROJECT_ROOT"/runtime/bin/*; do
        [ -f "$s" ] || continue
        local first_line
        first_line=$(head -n 1 "$s")
        if echo "$first_line" | grep -Eq 'bash|sh'; then
            bash -n "$s"
        elif echo "$first_line" | grep -q 'python'; then
            python3 -c "from pathlib import Path; import sys; p = Path(sys.argv[1]); compile(p.read_text(), str(p), 'exec')" "$s"
        fi
    done
    # brain_wiki is now a package (Phase 14.1 split) — syntax-check each submodule
    for _bw_mod in brain_wiki/__init__.py brain_wiki/frontmatter.py brain_wiki/pages.py brain_wiki/validators.py brain_wiki/writers.py; do
        python3 -c "from pathlib import Path; import sys; p = Path(sys.argv[1]); compile(p.read_text(), str(p), 'exec')" "$PROJECT_ROOT/runtime/lib/$_bw_mod"
    done
    python3 -c "from pathlib import Path; import sys; p = Path(sys.argv[1]); compile(p.read_text(), str(p), 'exec')" "$PROJECT_ROOT/runtime/lib/brain_index.py"
    python3 -c "from pathlib import Path; import sys; p = Path(sys.argv[1]); compile(p.read_text(), str(p), 'exec')" "$PROJECT_ROOT/runtime/mcp/server.py"
    grep -q "from tools_prd import" "$PROJECT_ROOT/runtime/mcp/server.py"
    grep -q "@mcp.tool()" "$PROJECT_ROOT/runtime/mcp/tools_prd.py"
    grep -q "def init_prd" "$PROJECT_ROOT/runtime/mcp/tools_prd.py"
    grep -q "def commit_prd" "$PROJECT_ROOT/runtime/mcp/tools_prd.py"
}
