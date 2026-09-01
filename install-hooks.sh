#!/usr/bin/env bash
# install-hooks.sh — Setup git hooks for Brain development
#
# Run from a git checkout. Destination is `git rev-parse --git-path hooks`
# (worktree-safe). Hooks resolve the checkout at runtime via
# `git rev-parse --show-toplevel`; the install-time path is not baked in.

set -euo pipefail

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "install-hooks.sh: run from a git checkout" >&2
    exit 1
fi

cd "$(git rev-parse --show-toplevel)"
HOOKS_DIR=$(git rev-parse --git-path hooks)
mkdir -p "$HOOKS_DIR"

echo ">>> Installing pre-commit and pre-push hooks into $HOOKS_DIR"

cat > "$HOOKS_DIR/pre-commit" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
# Fast index-aware policy gate. Full suite lives in pre-push.

CHECKOUT=$(git rev-parse --show-toplevel)

# Системные файлы коммитятся только в публичном чекауте, не в ~/brain.
_WRITE_GUARD=""
if [ -n "${BRAIN_SYSTEM_PATH:-}" ] && [ -x "${BRAIN_SYSTEM_PATH}/runtime/hooks/pre-commit-write-path" ]; then
    _WRITE_GUARD="${BRAIN_SYSTEM_PATH}/runtime/hooks/pre-commit-write-path"
elif [ -x "${CHECKOUT}/runtime/hooks/pre-commit-write-path" ]; then
    _WRITE_GUARD="${CHECKOUT}/runtime/hooks/pre-commit-write-path"
fi
if [ -n "${_WRITE_GUARD}" ]; then
    "${_WRITE_GUARD}" || exit 1
fi

# Системный слой в главной ветке правит только опознанный оператор.
_SYS_GUARD=""
if [ -n "${BRAIN_SYSTEM_PATH:-}" ] && [ -x "${BRAIN_SYSTEM_PATH}/runtime/hooks/pre-commit-system-guard" ]; then
    _SYS_GUARD="${BRAIN_SYSTEM_PATH}/runtime/hooks/pre-commit-system-guard"
elif [ -x "${CHECKOUT}/runtime/hooks/pre-commit-system-guard" ]; then
    _SYS_GUARD="${CHECKOUT}/runtime/hooks/pre-commit-system-guard"
fi
if [ -n "${_SYS_GUARD}" ]; then
    "${_SYS_GUARD}" || exit 1
fi

echo ">>> [pre-commit] Checking shell syntax"
for s in "${CHECKOUT}"/*.sh "${CHECKOUT}"/runtime/bin/*; do
    [ -f "$s" ] || continue
    if head -n 1 "$s" | grep -Eq 'bash|sh'; then
        bash -n "$s"
    fi
done

echo ">>> [pre-commit] UI anti-pattern lint (brain-uiux-lint)"
if [ -f "${CHECKOUT}/wiki/_views/brain-dashboard.html" ] && [ -x "${CHECKOUT}/runtime/bin/brain-uiux-lint" ]; then
    if ! "${CHECKOUT}/runtime/bin/brain-uiux-lint" --strict; then
        echo "ERROR: brain-uiux-lint found UI anti-patterns. Fix source CSS or add an exception (with reason) to wiki/_views/uiux-lint-baseline.json."
        exit 1
    fi
fi

echo ">>> [pre-commit] Personal data guard (brain-guard)"
# Документы по делам живут в папках дел, а не в репозитории системы.
# --added-only: журнал, архив задач и handoff несут имена по существу.
if [ -x "${CHECKOUT}/runtime/bin/brain-guard" ]; then
    if [ -f "${CHECKOUT}/.publish-secrets.local" ]; then
        if ! "${CHECKOUT}/runtime/bin/brain-guard" --added-only staged; then
            echo "ERROR: brain-guard нашёл персональные данные в индексе."
            echo "  Документ по делу? Его место — папка дела (knowledge/ или sources/ рядом с BRAIN.md)."
            echo "  Ложная тревога? Правила — в .publish-secrets.local."
            exit 1
        fi
    else
        if ! "${CHECKOUT}/runtime/bin/brain-guard" --generic-only --added-only staged; then
            echo "ERROR: brain-guard нашёл персональные данные в индексе."
            echo "  Документ по делу? Его место — папка дела (knowledge/ или sources/ рядом с BRAIN.md)."
            echo "  Ложная тревога? Правила — в .publish-secrets.local."
            exit 1
        fi
    fi
fi

echo ">>> [pre-commit] Quality check passed"
HOOK

cat > "$HOOKS_DIR/pre-push" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
# Isolated full suite. Child environment is an allowlist (env -i), not a
# named GIT_* denylist. Checkout is resolved at runtime.

CHECKOUT=$(git rev-parse --show-toplevel)
cd "$CHECKOUT"

_suite_env=()
_add_env() {
    local key="$1"
    local val="$2"
    [ -n "$val" ] || return 0
    _suite_env+=("${key}=${val}")
}
_add_env PATH "${PATH}"
_add_env HOME "${HOME:-/tmp}"
_add_env USER "${USER:-}"
_add_env LOGNAME "${LOGNAME:-}"
_add_env LANG "${LANG:-C.UTF-8}"
_add_env LC_ALL "${LC_ALL:-}"
_add_env LC_CTYPE "${LC_CTYPE:-}"
_add_env TERM "${TERM:-dumb}"
_add_env TMPDIR "${TMPDIR:-/tmp}"
_add_env TZ "${TZ:-}"
_add_env LD_LIBRARY_PATH "${LD_LIBRARY_PATH:-}"
_add_env SSL_CERT_FILE "${SSL_CERT_FILE:-}"
_add_env REQUESTS_CA_BUNDLE "${REQUESTS_CA_BUNDLE:-}"
_add_env CURL_CA_BUNDLE "${CURL_CA_BUNDLE:-}"

echo ">>> [pre-push] Running isolated smoke+pytest"
env -i -- "${_suite_env[@]}" bash --noprofile --norc -c '
set -euo pipefail
cd "$1"
if [ -f tests/run.sh ]; then
    echo ">>> [pre-push] Running smoke suite (tests/run.sh)"
    bash tests/run.sh
fi
if [ -d tests/python ] && ls tests/python/*.py >/dev/null 2>&1; then
    echo ">>> [pre-push] Running unit tests (pytest)"
    PYTHONPATH=./runtime/lib python3 -m pytest tests/python/ --quiet
else
    echo ">>> [pre-push] No tests/python suite — skipping pytest"
fi
' bash "$CHECKOUT"
HOOK

chmod +x "$HOOKS_DIR/pre-commit" "$HOOKS_DIR/pre-push"
echo ">>> Done. Hooks installed at $HOOKS_DIR"
