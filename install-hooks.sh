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

# Системные файлы коммитятся только в публичном чекауте, не в ~/brain.
_WRITE_GUARD=""
if [ -n "\${BRAIN_SYSTEM_PATH:-}" ] && [ -x "\${BRAIN_SYSTEM_PATH}/runtime/hooks/pre-commit-write-path" ]; then
    _WRITE_GUARD="\${BRAIN_SYSTEM_PATH}/runtime/hooks/pre-commit-write-path"
elif [ -x "\${PROJECT_ROOT}/runtime/hooks/pre-commit-write-path" ]; then
    _WRITE_GUARD="\${PROJECT_ROOT}/runtime/hooks/pre-commit-write-path"
fi
if [ -n "\$_WRITE_GUARD" ]; then
    "\$_WRITE_GUARD" || exit 1
fi

# Системный слой в главной ветке правит только опознанный оператор: правка
# ролей, доктрин и рантайма меняет поведение всех будущих запусков.
# Опознание положительное (терминал или файл операторской сессии), поэтому
# процесс без идентичности получает отказ, а не молчание.
if [ -x "\${PROJECT_ROOT}/runtime/hooks/pre-commit-system-guard" ]; then
    "\${PROJECT_ROOT}/runtime/hooks/pre-commit-system-guard" || exit 1
fi

# Git передаёт хуку своё окружение: GIT_INDEX_FILE указывает на index.lock
# основного чекаута, GIT_DIR — на его .git. Тесты запускают git в собственных
# временных репозиториях и наследуют эти переменные, поэтому их \`git add\` и
# \`git commit\` уходили в индекс живого репозитория. Проявлялось как четыре
# падения git-кейсов (47, 49, 95, 97) только внутри коммита — при отдельном
# прогоне те же кейсы зелёные. Снимаем всё окружение git до любых проверок.
unset GIT_INDEX_FILE GIT_DIR GIT_WORK_TREE GIT_PREFIX GIT_AUTHOR_DATE \\
      GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_EDITOR GIT_EXEC_PATH \\
      GIT_REFLOG_ACTION

echo ">>> [pre-commit] Checking shell syntax"
for s in "\${PROJECT_ROOT}"/*.sh "\${PROJECT_ROOT}"/runtime/bin/*; do
    [ -f "\$s" ] || continue
    if head -n 1 "\$s" | grep -Eq 'bash|sh'; then
        bash -n "\$s"
    fi
done

# cd до прогона, а не после: смоук-кейсы резолвят пути от cwd, и при коммите
# из git worktree cwd — это дерево worktree, а PROJECT_ROOT — основной чекаут.
# Кейсы искали runtime/bin/* рядом с собой и падали, из-за чего коммит из
# worktree был невозможен в принципе.
cd "\${PROJECT_ROOT}"

if [ -f "\${PROJECT_ROOT}/tests/run.sh" ]; then
    echo ">>> [pre-commit] Running smoke suite (tests/run.sh)"
    bash "\${PROJECT_ROOT}/tests/run.sh"
fi

echo ">>> [pre-commit] Running unit tests (pytest)"
# Use a relative path to avoid path issues
cd "\${PROJECT_ROOT}"
if [ -d tests/python ] && ls tests/python/*.py >/dev/null 2>&1; then
    PYTHONPATH="./runtime/lib" python3 -m pytest tests/python/ --quiet
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
