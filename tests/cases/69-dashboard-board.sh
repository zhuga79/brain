#!/usr/bin/env bash
# Test: Trello-style board (Доска) with status-aware action buttons.
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying dashboard board (kanban) rendering"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

# Колонка «Циклические» рисуется из вывода `systemctl --user list-timers`.
# Без подмены кейс проверял не вёрстку, а состав таймеров хоста: у оператора
# brain-* таймеры заведены и колонка была, на чистом раннере таймеров нет и
# кейс падал. Расписание задаёт сам кейс — как в 71-dashboard-cycle-run.
shim="$BRAIN_FACTORY_TMP/shim"; mkdir -p "$shim"
cat > "$shim/systemctl" <<'SH'
#!/usr/bin/env bash
case " $* " in
  *" list-timers "*)
    cat <<'TABLE'
NEXT                        LEFT    LAST                        PASSED  UNIT                       ACTIVATES
Sat 2026-05-30 16:20:00 UTC 10min   Sat 2026-05-30 16:10:00 UTC 1min    brain-provider-probe.timer brain-provider-probe.service
TABLE
    ;;
esac
exit 0
SH
chmod +x "$shim/systemctl"
export PATH="$shim:$PATH"

mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki" "$BRAIN_PATH/roles"
cat > "$BRAIN_PATH/tasks/active.md" <<'TASKS'
# Active Tasks

- [~] [P0] t-2026-05-30-prog — Срочная в работе
      role: developer   mode: solo
      by: claude-opus-3198
      acceptance: ok

- [ ] [P1] t-2026-05-30-q1 — Важная в очереди
      role: developer   mode: solo
      acceptance: ok

- [ ] [P2] t-2026-05-30-q2 — Обычная в очереди
      role: pm   mode: solo
      acceptance: ok
TASKS
printf '# Done\n' > "$BRAIN_PATH/tasks/done.md"
printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"
printf '# Developer\n' > "$BRAIN_PATH/roles/developer.md"

brain-dashboard export > /dev/null
H="$BRAIN_PATH/wiki/_views/brain-dashboard.html"
[ -f "$H" ] || { echo "FAILED: html not created"; exit 1; }

# Редизайн 73f18f2 заменил доску единым блоком #task-operations, а колонки —
# группами по готовности: что можно запускать, что уже идёт, что стоит.
grep -q 'id="task-operations"' "$H" || { echo "FAILED: task operations section missing"; exit 1; }
for col in 'Готовы к запуску' 'В работе' 'Циклические'; do
  grep -qF "$col" "$H" || { echo "FAILED: column '$col' missing"; exit 1; }
done
echo "OK: three columns present"

# Status-aware buttons: in-progress card has restart/pause/cancel/status
# «Перезапустить» ушло вместе с доской: у задачи в работе теперь Статус,
# Пауза, Завершить и Отменить — перезапуск делается через Ручной запуск.
for b in 'Статус' 'Пауза' 'Завершить' 'Отменить'; do
  grep -qF ">$b</button>" "$H" || { echo "FAILED: progress button '$b' missing"; exit 1; }
done
# queued card has launch
grep -qF '>Запустить</button>' "$H" || { echo "FAILED: queue button Запустить missing"; exit 1; }
echo "OK: status-aware buttons present"

# big task title + real action wiring (data attributes / endpoints)
grep -qF "Срочная в работе" "$H" || { echo "FAILED: task title missing"; exit 1; }
grep -q "data-kb-action='launch'" "$H" || { echo "FAILED: launch action wiring missing"; exit 1; }
# Операции очереди привязаны через data-action (обращение к brain-task),
# а data-kb-action остался у операций запуска.
grep -q "data-action='release'" "$H" || { echo "FAILED: release action wiring missing"; exit 1; }
grep -q "data-action='block'" "$H" || { echo "FAILED: block action wiring missing"; exit 1; }
echo "OK: real action wiring present"

# priority ranking: P1 queued card before P2 queued card
p1=$(grep -boF "Важная в очереди" "$H" | head -1 | cut -d: -f1)
p2=$(grep -boF "Обычная в очереди" "$H" | head -1 | cut -d: -f1)
[ "$p1" -lt "$p2" ] || { echo "FAILED: queue not ranked by priority"; exit 1; }
echo "OK: cards ranked by priority"

echo "dashboard board test PASSED"
