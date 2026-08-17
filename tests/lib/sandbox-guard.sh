#!/usr/bin/env bash
# tests/lib/sandbox-guard.sh — отказ работать по боевым данным.
#
# Подключается первой строкой каждого кейса:
#
#     . "$(dirname "${BASH_SOURCE[0]}")/../lib/sandbox-guard.sh"
#
# Зачем. Кейсы вызывают brain-task, brain-lock и setup-brain-v2.sh, которые
# пишут в $BRAIN_PATH и коммитят в git. Запущенный в обход tests/run.sh кейс
# наследует боевой BRAIN_PATH и уничтожает рабочую очередь — 2026-08-10 так
# были потеряны 36 задач и 78 файлов handoff/, причём мусор ушёл в git
# автокоммитами brain-task.
#
# Раннер выставляет BRAIN_TEST_SANDBOX=1 и разворачивает Brain во временном
# HOME.
#
# 2026-08-16: признаком безопасности было расположение пути (BRAIN_PATH
# внутри ${TMPDIR:-/tmp}), а не свойство самого дерева. Рабочие git worktree
# лежали в /tmp/wt-federation и /tmp/wt-cwd; guard счёл их песочницей —
# префикс совпал, BRAIN_TEST_SANDBOX где-то протёк в окружение — и пропустил
# bootstrap внутрь боевого дерева. Тот прогон переписал roles/*.md и
# tasks/active.md рабочего чекаута. Путь ничего не говорит о намерении:
# любой каталог под /tmp годился бы точно так же.
#
# Взамен — файл-маркер, самосогласованный со своим каталогом: раннер
# (tests/run.sh) создаёт временный каталог через mktemp -d и пишет в маркер
# ЕГО ЖЕ канонический путь. Guard проверяет: маркер существует, его
# содержимое совпадает с путём каталога, в котором он лежит, и что BRAIN_PATH
# — потомок именно этого каталога. Значение появляется только как побочный
# эффект настоящего `mktemp -d` конкретно этого прогона: его нельзя
# унаследовать по ошибке (протёкшая переменная не создаёт файла), и его
# нельзя было выставить заранее — а до утечки самого mktemp-каталога
# подделать содержимое (путь, которого ещё не существовало) невозможно.
# Разработчику для этого ничего вручную делать не нужно — раннер делает всё
# сам при каждом прогоне.

_guard_die() {
    echo "ОТКАЗ: $1" >&2
    echo >&2
    echo "  Кейсы запускаются только через раннер:" >&2
    echo "      bash tests/run.sh [шаблон]" >&2
    echo >&2
    echo "  Прямой запуск работает по боевому \$BRAIN_PATH и уничтожает" >&2
    echo "  рабочие данные — очередь задач, wiki, handoff." >&2
    exit 2
}

[ -n "${BRAIN_TEST_SANDBOX:-}" ] \
    || _guard_die "нет маркера песочницы (BRAIN_TEST_SANDBOX)"

[ -n "${BRAIN_PATH:-}" ] \
    || _guard_die "BRAIN_PATH не задан"

[ -n "${BRAIN_TEST_SANDBOX_MARKER:-}" ] \
    || _guard_die "не задан файл-маркер песочницы (BRAIN_TEST_SANDBOX_MARKER) — кейс запущен не через tests/run.sh"

[ -f "$BRAIN_TEST_SANDBOX_MARKER" ] \
    || _guard_die "файл-маркер песочницы не найден: $BRAIN_TEST_SANDBOX_MARKER"

_guard_marker_dir="$(CDPATH= cd -- "$(dirname -- "$BRAIN_TEST_SANDBOX_MARKER")" 2>/dev/null && pwd -P)" \
    || _guard_die "не удалось разрешить каталог маркера: $BRAIN_TEST_SANDBOX_MARKER"

_guard_marker_content="$(cat "$BRAIN_TEST_SANDBOX_MARKER" 2>/dev/null || true)"
[ "$_guard_marker_content" = "$_guard_marker_dir" ] \
    || _guard_die "файл-маркер песочницы не самосогласован (подделан, устарел или скопирован из другого прогона)"

# BRAIN_PATH должен быть потомком каталога, которому принадлежит маркер, —
# не просто лежать где-то под /tmp. Symlink'и разрешаем: ~/brain — симлинк на
# рабочее дерево, без readlink проверка обходится.
_guard_real_brain="$(readlink -f "$BRAIN_PATH" 2>/dev/null || echo "$BRAIN_PATH")"

case "$_guard_real_brain" in
    "$_guard_marker_dir"/*) ;;
    *) _guard_die "BRAIN_PATH вне каталога песочницы раннера: $_guard_real_brain (песочница: $_guard_marker_dir)" ;;
esac

unset _guard_real_brain _guard_marker_dir _guard_marker_content
