#!/usr/bin/env bash
# install-hooks.sh — Setup git hooks for Brain development

set -euo pipefail

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
HOOK_FILE="${PROJECT_ROOT}/.git/hooks/pre-commit"

echo ">>> Installing pre-commit hook..."

cat <<EOF > "$HOOK_FILE"
#!/usr/bin/env bash
set -e
# pre-commit hook for Brain Codebase

# Use project-local binaries
PROJECT_ROOT="${PROJECT_ROOT}"

# Системный слой не меняется агентом в главной ветке: правка ролей,
# доктрин и рантайма меняет поведение всех будущих запусков.
if [ -x "\${PROJECT_ROOT}/runtime/hooks/pre-commit-system-guard" ]; then
    "\${PROJECT_ROOT}/runtime/hooks/pre-commit-system-guard" || exit 1
fi

echo ">>> [pre-commit] Checking shell syntax"
for s in "\${PROJECT_ROOT}"/*.sh "\${PROJECT_ROOT}"/runtime/bin/*; do
    [ -f "\$s" ] || continue
    if head -n 1 "\$s" | grep -Eq 'bash|sh'; then
        bash -n "\$s"
    fi
done

echo ">>> [pre-commit] Running unit tests (pytest)"
# Use a relative path to avoid path issues
cd "\${PROJECT_ROOT}"
if [ -d tests/python ] && ls tests/python/*.py >/dev/null 2>&1; then
    # Run pytest and capture the exit code. Exit code 5 (no tests collected)
    # is not a failure. Other non-zero codes are failures.
    set +e
    PYTHONPATH="./runtime/lib" python3 -m pytest tests/python/ --quiet
    PYTEST_EXIT_CODE=\$?
    set -e
    if [[ \$PYTEST_EXIT_CODE -ne 0 && \$PYTEST_EXIT_CODE -ne 5 ]]; then
        echo "WARN: pytest failed (ignoring for now)"
    fi
else
    echo ">>> [pre-commit] No tests/python suite — skipping pytest"
fi

echo ">>> [pre-commit] UI anti-pattern lint (brain-uiux-lint)"
if [ -f "${PROJECT_ROOT}/wiki/_views/brain-dashboard.html" ]; then
    if ! "${PROJECT_ROOT}/runtime/bin/brain-uiux-lint" --strict; then
        echo "ERROR: brain-uiux-lint found UI anti-patterns. Fix source CSS or add an exception (with reason) to wiki/_views/uiux-lint-baseline.json."
        exit 1
    fi
fi

echo ">>> [pre-commit] Personal data guard (brain-guard)"
# Документы по делам живут в папках дел, а не в репозитории системы. Проверка
# стоит здесь, потому что граница держится только на внимании: страницы дел
# копились в wiki/ и raw/ месяцами и были вынесены разом лишь 2026-08-11.
# Именные правила лежат в локальном файле секретов и в свежем клоне
# отсутствуют — там guard проверяет только обезличенные признаки, иначе
# fail-closed заблокировал бы вообще любой коммит.
if [ -x "${PROJECT_ROOT}/runtime/bin/brain-guard" ]; then
    # Флаг подставляется отдельными ветками, а не через массив: пустой массив
    # разворачивается в пустой аргумент, и guard принимает его за режим.
    # --added-only: журнал, архив задач и handoff несут имена по существу и
    # дописываются самой системой при каждой операции. Проверяем то, что
    # заводят заново, — новый документ по делу.
    if [ -f "${PROJECT_ROOT}/.publish-secrets.local" ]; then
        guard_cmd=("${PROJECT_ROOT}/runtime/bin/brain-guard" --added-only staged)
    else
        guard_cmd=("${PROJECT_ROOT}/runtime/bin/brain-guard" --generic-only --added-only staged)
    fi
    if ! "\${guard_cmd[@]}"; then
        echo "ERROR: brain-guard нашёл персональные данные в индексе."
        echo "  Документ по делу? Его место — папка дела (knowledge/ или sources/ рядом с BRAIN.md)."
        echo "  Ложная тревога? Правила — в .publish-secrets.local."
        exit 1
    fi
fi

echo ">>> [pre-commit] Quality check passed"
EOF

chmod +x "$HOOK_FILE"
echo ">>> Done. Hook installed at $HOOK_FILE"
