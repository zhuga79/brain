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
# HOME. Guard требует обоих признаков: маркера и того, что BRAIN_PATH
# действительно лежит во временном каталоге, — маркер сам по себе можно
# выставить руками, а путь сам по себе ничего не говорит о намерении.

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

# Путь должен лежать во временном каталоге. Сравниваем по разрешённому пути:
# ~/brain — симлинк на рабочее дерево, и без readlink проверка обходится.
_guard_real_brain="$(readlink -f "$BRAIN_PATH" 2>/dev/null || echo "$BRAIN_PATH")"
_guard_tmp="$(readlink -f "${TMPDIR:-/tmp}" 2>/dev/null || echo "${TMPDIR:-/tmp}")"

case "$_guard_real_brain" in
    "$_guard_tmp"/*) ;;
    *) _guard_die "BRAIN_PATH указывает вне временного каталога: $_guard_real_brain" ;;
esac

unset _guard_real_brain _guard_tmp
