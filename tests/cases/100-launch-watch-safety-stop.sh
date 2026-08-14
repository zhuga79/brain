#!/usr/bin/env bash
# case: launch-watch-safety-stop — t-2026-08-14-launch-watch-loop-safety-stop
#
# Инцидент 2026-08-14T20:09Z. Команда
#
#     brain-launch --watch --auto-next --dry-run
#
# — по собственной справке «показать план auto-next без side effects» — за две
# минуты пометила [~] одиннадцать задач из четырнадцати, взяла задачу с
# surface: interactive и gate: approval, захватила всю доступную очередь разом
# и оставила задачи с `by:` одного агента и локом другого.
#
# Кейс воспроизводит исходный сценарий на ИЗОЛИРОВАННОМ дереве: собственный
# BRAIN_PATH во временном каталоге, собственный git-репозиторий, подставной
# brain-launch. Боевое дерево не участвует.
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

_LIBPATH="$PROJECT_ROOT/runtime/lib"
INTERACTIVE_ID="t-2026-08-14-user-hp-sync"

# ── Изолированное дерево: очередь инцидента ──
td=$(mktemp -d)
ALL_TMPDIRS+=("$td")
mkdir -p "$td/tasks" "$td/wiki" "$td/.locks"
printf '# Done Tasks\n\n' > "$td/tasks/done.md"
printf '# Log\n\n' > "$td/wiki/log.md"

{
  printf '# Active Tasks\n\n'
  # Задача-ловушка: interactive + gate, и она же самая приоритетная.
  # Без фильтра поверхности headless auto-next заберёт именно её.
  printf -- '- [ ] [P0] %s — Sync HP data with the owner\n' "$INTERACTIVE_ID"
  printf -- '      role: developer   mode: solo\n'
  printf -- '      surface: interactive\n'
  printf -- '      gate: approval\n'
  printf -- '      acceptance: owner confirmed\n\n'
  for i in $(seq -w 1 13); do
    printf -- '- [ ] [P1] t-watch-case-%s — Headless task %s\n' "$i" "$i"
    printf -- '      role: developer   mode: solo\n'
    printf -- '      acceptance: done\n\n'
  done
} > "$td/tasks/active.md"

git -C "$td" init -q
git -C "$td" config user.email case@example.invalid
git -C "$td" config user.name case
git -C "$td" add -A
git -C "$td" commit -qm "queue snapshot"

export BRAIN_PATH="$td"
export BRAIN_SKIP_OPERATOR_ENV=1

_active_sha() { sha256sum "$td/tasks/active.md" | cut -d' ' -f1; }
_commits()    { git -C "$td" rev-list --count HEAD; }
_lock_count() { find "$td/.locks" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l; }
_in_progress() { grep -c '^- \[~\]' "$td/tasks/active.md" || true; }

# ── 1. --dry-run в комбинации с --watch --auto-next не пишет ничего ──
echo ">>> brain-launch --watch --auto-next --dry-run пишет ноль байт"
sha_before=$(_active_sha)
commits_before=$(_commits)

# Таймаут обязателен: до исправления --dry-run терялся, и эта же команда
# уходила в настоящий бесконечный watch-loop. Без таймаута кейс не падал бы,
# а висел.
set +e
timeout 30 brain-launch --watch --auto-next --dry-run > "$td/dry.log" 2>&1
rc=$?
set -e
[ "$rc" -ne 124 ] || {
  echo "FAILED: --dry-run ушёл в настоящий watch-loop (таймаут 30s)"
  tail -20 "$td/dry.log"
  exit 1
}
[ "$rc" -eq 0 ] || { echo "FAILED: dry-run вернул rc=$rc"; cat "$td/dry.log"; exit 1; }

grep -qi "DRY-RUN" "$td/dry.log" || {
  echo "FAILED: в выводе нет пометки DRY-RUN"; cat "$td/dry.log"; exit 1;
}
[ "$(_active_sha)" = "$sha_before" ] || {
  echo "FAILED: dry-run изменил active.md"; git -C "$td" diff -- tasks/active.md; exit 1;
}
[ "$(_commits)" = "$commits_before" ] || { echo "FAILED: dry-run сделал git-коммит"; exit 1; }
[ ! -d "$td/council" ] || { echo "FAILED: dry-run создал council/"; exit 1; }
[ "$(_lock_count)" -eq 0 ] || { echo "FAILED: dry-run захватил лок"; exit 1; }
[ "$(_in_progress)" -eq 0 ] || { echo "FAILED: dry-run пометил задачи [~]"; exit 1; }
if command -v tmux >/dev/null 2>&1; then
  tmux ls 2>/dev/null | grep -q "^brain-" && { echo "FAILED: dry-run поднял tmux-сессию"; exit 1; }
fi
echo "OK: dry-run без единой записи"

# ── 2. interactive-задача не попадает в headless auto-next ──
echo ">>> план auto-next не называет interactive-задачу"
grep -q "$INTERACTIVE_ID" "$td/dry.log" && {
  echo "FAILED: план назвал interactive-задачу $INTERACTIVE_ID"
  cat "$td/dry.log"
  exit 1
}
grep -q "t-watch-case-01" "$td/dry.log" || {
  echo "FAILED: план не назвал первую headless-задачу"
  cat "$td/dry.log"
  exit 1
}
next_json=$(brain-task next --headless-only --json)
python3 -c "
import json, sys
data = json.loads(sys.argv[1])
assert data['task']['id'] == 't-watch-case-01', data
" "$next_json" || { echo "FAILED: headless next вернул не ту задачу: $next_json"; exit 1; }
echo "OK: interactive остаётся вне headless auto-next"

# ── 3. Живой цикл на падающем запуске: WIP=1 и стоп по череде отказов ──
echo ">>> watch-loop с падающим brain-launch не проходит очередь насквозь"
stub="$td/stub-bin"
mkdir -p "$stub"
cat > "$stub/brain-launch" <<'STUB'
#!/usr/bin/env bash
echo "stub brain-launch: refusing to run $*" >&2
exit 1
STUB
chmod +x "$stub/brain-launch"

set +e
PATH="$stub:$PATH" \
PYTHONPATH="${_LIBPATH}${PYTHONPATH:+:${PYTHONPATH}}" \
  timeout 90 python3 -m brain_launch_watch "$td" "case-watch-$$" \
    --interval 0 --sync-interval 0 --ops-interval 0 \
    --wip 1 --max-failures 2 \
    > "$td/live.log" 2>&1
live_rc=$?
set -e
wait_for_index_rebuild "$td"

[ "$live_rc" -ne 124 ] || {
  echo "FAILED: цикл не остановился по череде отказов (таймаут 90s)"
  tail -20 "$td/live.log"
  exit 1
}
[ "$live_rc" -eq 1 ] || {
  echo "FAILED: цикл на падающем запуске вернул rc=$live_rc (ожидался 1)"
  cat "$td/live.log"
  exit 1
}
grep -qi "consecutive launch failures" "$td/live.log" || {
  echo "FAILED: цикл не сообщил о стопе по череде отказов"
  cat "$td/live.log"
  exit 1
}

started=$(grep -c 'task-start' "$td/wiki/log.md" || true)
[ "$started" -le 2 ] || {
  echo "FAILED: цикл взял $started задач при max-failures=2"
  grep 'task-start' "$td/wiki/log.md"
  exit 1
}
[ "$(_in_progress)" -eq 0 ] || {
  echo "FAILED: после остановки остались задачи [~]:"
  grep '^- \[~\]' "$td/tasks/active.md"
  exit 1
}
[ "$(_lock_count)" -eq 0 ] || {
  echo "FAILED: после остановки остались локи:"
  ls "$td/.locks"
  exit 1
}
grep -q "$INTERACTIVE_ID" "$td/wiki/log.md" && {
  echo "FAILED: цикл тронул interactive-задачу"
  exit 1
}
echo "OK: одна задача за раз, возврат в очередь, стоп по отказам"

# ── 4. Каждый [ ]→[~] несёт лок того же агента, что и by: ──
echo ">>> take захватывает лок тем же agent-id, что уходит в by:"
brain-task take t-watch-case-02 --as case-agent-a >/dev/null
grep -A5 't-watch-case-02' "$td/tasks/active.md" | grep -q 'by: case-agent-a' || {
  echo "FAILED: by: не записан"; exit 1;
}
[ -f "$td/.locks/t-watch-case-02/owner" ] || { echo "FAILED: take не создал лок"; exit 1; }
lock_owner=$(cut -d'|' -f1 < "$td/.locks/t-watch-case-02/owner")
[ "$lock_owner" = "case-agent-a" ] || {
  echo "FAILED: владелец лока '$lock_owner' ≠ by: case-agent-a"; exit 1;
}

set +e
brain-task take t-watch-case-02 --as case-agent-b >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: чужой агент смог взять занятую задачу"; exit 1; }
echo "OK: лок и by: называют одного агента"

# ── 5. Расхождение владельцев разбирается штатной командой ──
echo ">>> brain-task reconcile разбирает «владелец задачи ≠ владелец лока»"
printf 'reviewer-tmux-bc20|%s|600\n' "$(date +%s)" > "$td/.locks/t-watch-case-02/owner"

set +e
brain-task release t-watch-case-02 --as case-agent-a >/dev/null 2>&1
rc_task_owner=$?
brain-task release t-watch-case-02 --as reviewer-tmux-bc20 >/dev/null 2>&1
rc_lock_owner=$?
set -e
[ "$rc_task_owner" -ne 0 ] && [ "$rc_lock_owner" -ne 0 ] || {
  echo "FAILED: расхождение владельцев должно отвергаться обеими сторонами"
  exit 1
}

set +e
report=$(brain-task reconcile 2>&1)
rc_report=$?
set -e
[ "$rc_report" -ne 0 ] || { echo "FAILED: reconcile не увидел расхождения: $report"; exit 1; }
echo "$report" | grep -q "owner_mismatch" || {
  echo "FAILED: reconcile не назвал вид расхождения: $report"; exit 1;
}

brain-task reconcile --fix >/dev/null
wait_for_index_rebuild "$td"
grep -q '^- \[ \] \[P1\] t-watch-case-02' "$td/tasks/active.md" || {
  echo "FAILED: reconcile --fix не вернул задачу в очередь"
  grep 't-watch-case-02' "$td/tasks/active.md"
  exit 1
}
[ ! -d "$td/.locks/t-watch-case-02" ] || { echo "FAILED: reconcile --fix не снял лок"; exit 1; }
brain-task reconcile >/dev/null || { echo "FAILED: после fix очередь всё ещё расходится"; exit 1; }
echo "OK: расхождение снимается без ручного вмешательства"

wait_for_index_rebuild "$td"
echo ">>> launch-watch safety-stop checks passed"
