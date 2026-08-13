#!/usr/bin/env bash
# Test for dashboard task tree rendering (themed, collapsible groups).
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying dashboard task tree rendering"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki" "$BRAIN_PATH/roles"
# Three tasks exercising each theme path:
#  - tag '#foo'                -> theme "foo"
#  - id slug t-...-bar-baz     -> theme "bar"
#  - non-dated id 'misc-...'   -> theme "other"
cat > "$BRAIN_PATH/tasks/active.md" <<'TASKS'
# Active Tasks

- [ ] [P3] t-2026-05-29-foo-alpha — Foo themed task
      role: developer   mode: solo
      tags: #foo
      acceptance: rendered under Foo theme.

- [ ] [P2] t-2026-05-29-bar-baz — Bar themed task
      role: developer   mode: solo
      acceptance: rendered under Bar theme.

- [ ] [P1] misc-other-1 — Other themed task
      role: developer   mode: solo
      acceptance: rendered under Other theme.
TASKS
printf '# Done Tasks\n' > "$BRAIN_PATH/tasks/done.md"
printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"
printf '# Wiki Index\n' > "$BRAIN_PATH/wiki/index.md"
printf '# Developer\n' > "$BRAIN_PATH/roles/developer.md"

brain-dashboard export > /dev/null
HTML_FILE="$BRAIN_PATH/wiki/_views/brain-dashboard.html"
[ -f "$HTML_FILE" ] || { echo "FAILED: brain-dashboard.html not created"; exit 1; }

debug_on_fail() {
    local pattern="$1"; local msg="$2"
    grep -q "$pattern" "$HTML_FILE" || {
        echo "FAILED: $msg"
        grep -C 6 "Active Queue" "$HTML_FILE" || true
        exit 1
    }
}

# 1. Section preserved.
debug_on_fail 'section id="task-operations"' "dashboard missing section id=task-operations"
echo "OK: section id=task-operations present"

# 2. Collapsible themed grouping present.
# Группировка по темам заменена на свёртки вторичных групп внутри
# #task-operations (редизайн 73f18f2).
debug_on_fail '<details class="secondary-group"' "dashboard missing secondary task groups"
echo "OK: secondary task groups present"

# 3. Task id rendered as small monospace code.
debug_on_fail "<span class='mono small'>t-2026-05-29-bar-baz</span>" "missing mono small task id"
echo "OK: mono small task id present"

# 4. Filter contract preserved (data-* attributes intact for the filter JS).
debug_on_fail "data-filter-row='task'" "filter contract broken: data-filter-row missing"
echo "OK: data-filter-row preserved"

# 5. Группировка. Тематические группы (по тегу, по слагу id, «Other») ушли
# вместе с редизайном 73f18f2: задачи группируются по готовности к запуску,
# а вторичные группы — свёртки внутри #task-operations. Проверка темы снята
# как проверка несуществующей функции; на её место — группировка, которая
# есть на самом деле.
debug_on_fail 'Готовы к запуску' "missing ready-to-launch group"
debug_on_fail 'misc-other-1' "task with a non-dated id is not rendered"
echo "OK: задачи сгруппированы по готовности, id любого вида отображается"

echo "Dashboard task tree test PASSED."
