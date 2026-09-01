#!/usr/bin/env bash
# case: queue-idempotency — повтор команды тем же агентом не ломает работу
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying queue contract is idempotent and owner-aware"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1

tid="$(brain-task add "Проба идемпотентности" --role developer 2>&1 | tail -1 | sed 's/added: //')"
[ -n "$tid" ] || { echo "FAILED: задача не создана"; exit 1; }

# ── 1. Последовательность из MEMORY.md: сначала лок, затем take ──
# take безусловно зовёт acquire, а тот не отличал «занято другим» от «уже моё»,
# и рекомендованный порядок действий возвращал ошибку.
brain-lock acquire "$tid" --as me --ttl 600 >/dev/null || { echo "FAILED: acquire не прошёл"; exit 1; }
out="$(brain-lock acquire "$tid" --as me 2>&1)"
grep -qi "ok" <<< "$out" || { echo "FAILED: повторный acquire своим агентом: $out"; exit 1; }
brain-task take "$tid" --as me >/dev/null || { echo "FAILED: take после acquire"; exit 1; }
echo "OK: acquire → take работает"

# ── 2. Повтор той же команды тем же агентом ──
brain-task take "$tid" --as me >/dev/null || { echo "FAILED: повторный take"; exit 1; }
echo "OK: take идемпотентен"

# ── 3. Чужой агент задачу не забирает ──
set +e
brain-task take "$tid" --as someone-else >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: чужой агент забрал заблокированную задачу"; exit 1; }
echo "OK: чужой take отклонён"

snapshot_dir="$(mktemp -d)"
ALL_TMPDIRS+=("$snapshot_dir")
cp "$BRAIN_PATH/tasks/active.md" "$snapshot_dir/active.before"
cp "$BRAIN_PATH/tasks/done.md" "$snapshot_dir/done.before"
cp "$BRAIN_PATH/wiki/log.md" "$snapshot_dir/log.before"
cp "$BRAIN_PATH/.locks/$tid/owner" "$snapshot_dir/owner.before"

# ── 4. release без владельца отклоняется ──
set +e
out="$(brain-task release "$tid" 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: release без --as прошёл"; exit 1; }
grep -q "укажи исполнителя" <<< "$out" || { echo "FAILED: непонятная причина отказа: $out"; exit 1; }

set +e
out="$(brain-lock release "$tid" 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: brain-lock release без --as снял лок"; exit 1; }
grep -q "укажи владельца" <<< "$out" || { echo "FAILED: непонятная причина отказа: $out"; exit 1; }
echo "OK: снятие лока требует владельца"

# ── 5. Чужой release/block/complete не мутирует очередь и лок ──
set +e
out="$(brain-task release "$tid" --as intruder 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: чужой release прошёл"; exit 1; }
grep -Eq "task owned by me, not intruder|lock owned by me, not intruder" <<< "$out" || {
  echo "FAILED: release wrong-owner error unclear: $out"; exit 1;
}
cmp -s "$snapshot_dir/active.before" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: intruder release changed active.md"; exit 1; }
cmp -s "$snapshot_dir/done.before" "$BRAIN_PATH/tasks/done.md" || { echo "FAILED: intruder release changed done.md"; exit 1; }
cmp -s "$snapshot_dir/log.before" "$BRAIN_PATH/wiki/log.md" || { echo "FAILED: intruder release changed wiki/log.md"; exit 1; }
cmp -s "$snapshot_dir/owner.before" "$BRAIN_PATH/.locks/$tid/owner" || { echo "FAILED: intruder release changed lock owner"; exit 1; }

set +e
out="$(brain-task block "$tid" "need info" --as intruder 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: чужой block прошёл"; exit 1; }
grep -Eq "task owned by me, not intruder|lock owned by me, not intruder" <<< "$out" || {
  echo "FAILED: block wrong-owner error unclear: $out"; exit 1;
}
cmp -s "$snapshot_dir/active.before" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: intruder block changed active.md"; exit 1; }
cmp -s "$snapshot_dir/done.before" "$BRAIN_PATH/tasks/done.md" || { echo "FAILED: intruder block changed done.md"; exit 1; }
cmp -s "$snapshot_dir/log.before" "$BRAIN_PATH/wiki/log.md" || { echo "FAILED: intruder block changed wiki/log.md"; exit 1; }
cmp -s "$snapshot_dir/owner.before" "$BRAIN_PATH/.locks/$tid/owner" || { echo "FAILED: intruder block changed lock owner"; exit 1; }

set +e
out="$(brain-task complete "$tid" --as intruder --model evil-model-1 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: чужой complete прошёл"; exit 1; }
grep -Eq "task owned by me, not intruder|lock owned by me, not intruder" <<< "$out" || {
  echo "FAILED: complete wrong-owner error unclear: $out"; exit 1;
}
cmp -s "$snapshot_dir/active.before" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: intruder complete changed active.md"; exit 1; }
cmp -s "$snapshot_dir/done.before" "$BRAIN_PATH/tasks/done.md" || { echo "FAILED: intruder complete changed done.md"; exit 1; }
cmp -s "$snapshot_dir/log.before" "$BRAIN_PATH/wiki/log.md" || { echo "FAILED: intruder complete changed wiki/log.md"; exit 1; }
cmp -s "$snapshot_dir/owner.before" "$BRAIN_PATH/.locks/$tid/owner" || { echo "FAILED: intruder complete changed lock owner"; exit 1; }
echo "OK: wrong owner cannot mutate queue or lock"

# ── 6. Владелец снимает и повторяет ──
brain-task release "$tid" --as me >/dev/null || { echo "FAILED: release владельцем"; exit 1; }
brain-task release "$tid" --as me >/dev/null || { echo "FAILED: повторный release"; exit 1; }
echo "OK: release идемпотентен"

# ── 7. --force снимает чужой лок явно ──
brain-lock acquire "$tid" --as someone-else >/dev/null
brain-lock release "$tid" --force >/dev/null || { echo "FAILED: --force не сработал"; exit 1; }
[ "$(brain-lock status "$tid")" = "free" ] || { echo "FAILED: лок остался после --force"; exit 1; }
echo "OK: --force снимает чужой лок явно"

# ── 8. complete без --as не закрывает задачу ──
brain-task take "$tid" --as me >/dev/null
set +e
out="$(brain-task complete "$tid" 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: complete без --as прошёл"; exit 1; }
grep -q "укажи исполнителя" <<< "$out" || { echo "FAILED: непонятная причина отказа: $out"; exit 1; }
grep -q "$tid" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: задача закрыта без владельца"; exit 1; }
echo "OK: complete требует владельца"

# ── 9. stale lock does not reject the owner's complete ──
# t-2026-08-14-lock-ttl-versus-agent-task-dur: expiry frees the lock for
# someone else, it does not veto the holder finishing their own work.
python3 - "$BRAIN_PATH/.locks/$tid/owner" <<'PY'
from pathlib import Path
import time
import sys
path = Path(sys.argv[1])
owner, _ts, ttl = path.read_text(encoding="utf-8").strip().split("|")
path.write_text(f"{owner}|{int(time.time())-1000}|{ttl}\n", encoding="utf-8")
PY
BRAIN_AGENT_MODEL=probe-model-1 brain-task complete "$tid" --as me >/dev/null || {
  echo "FAILED: owner complete after TTL expiry"
  exit 1
}
grep -q "$tid" "$BRAIN_PATH/tasks/done.md" || { echo "FAILED: задача не попала в done"; exit 1; }
[ ! -e "$BRAIN_PATH/.locks/$tid/owner" ] || { echo "FAILED: lock remained after owner complete"; exit 1; }
echo "OK: задача закрыта владельцем"

# ── 10. Открытая задача под локом закрывается только владельцем лока ──
# Между `brain-lock acquire` и `brain-task take` задача остаётся `[ ]`. У неё нет
# `by:`, и до t-2026-08-14-completion-open-lock-ownership завершение в этом окне
# не сверяло вообще ничего — закрыть чужую взятую задачу мог любой агент.
tid2="$(brain-task add "Открытая под локом" --role developer 2>&1 | tail -1 | sed 's/added: //')"
[ -n "$tid2" ] || { echo "FAILED: вторая задача не создана"; exit 1; }
brain-lock acquire "$tid2" --as me --ttl 600 >/dev/null || { echo "FAILED: acquire на открытой задаче"; exit 1; }
grep -q -- "- \[ \].*$tid2 —" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: задача должна остаться open"; exit 1; }

cp "$BRAIN_PATH/tasks/active.md" "$snapshot_dir/active.open.before"
cp "$BRAIN_PATH/tasks/done.md" "$snapshot_dir/done.open.before"
cp "$BRAIN_PATH/wiki/log.md" "$snapshot_dir/log.open.before"
cp "$BRAIN_PATH/.locks/$tid2/owner" "$snapshot_dir/owner.open.before"
set +e
out="$(brain-task complete "$tid2" --as intruder --model evil-model-1 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: чужой complete закрыл открытую задачу под локом"; exit 1; }
grep -q "lock owned by me, not intruder" <<< "$out" || {
  echo "FAILED: open-task complete error unclear: $out"; exit 1;
}
cmp -s "$snapshot_dir/active.open.before" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: intruder complete changed active.md"; exit 1; }
cmp -s "$snapshot_dir/done.open.before" "$BRAIN_PATH/tasks/done.md" || { echo "FAILED: intruder complete changed done.md"; exit 1; }
cmp -s "$snapshot_dir/log.open.before" "$BRAIN_PATH/wiki/log.md" || { echo "FAILED: intruder complete changed wiki/log.md"; exit 1; }
cmp -s "$snapshot_dir/owner.open.before" "$BRAIN_PATH/.locks/$tid2/owner" || { echo "FAILED: intruder complete changed lock owner"; exit 1; }
[ ! -e "$BRAIN_PATH/tasks/.taskfile-complete/$tid2.json" ] || { echo "FAILED: intruder complete wrote a journal"; exit 1; }
echo "OK: открытую задачу под локом чужой не закрывает"

BRAIN_AGENT_MODEL=probe-model-1 brain-task complete "$tid2" --as me >/dev/null || {
  echo "FAILED: владелец лока не смог закрыть открытую задачу"
  exit 1
}
grep -q "$tid2" "$BRAIN_PATH/tasks/done.md" || { echo "FAILED: открытая задача не попала в done"; exit 1; }
echo "OK: владелец лока закрывает открытую задачу"

# ── 11. Открытая задача под локом не блокируется посторонним ──
# t-2026-08-15-block-on-open-task-under-forei: та же расстановка, что в п.10, но
# другой мутирующий путь. Гвардия стояла только на ветке `[~]`, поэтому чужой
# агент не мог закрыть задачу, зато мог выбить её из очереди в `[!]`. Проверка
# сформулирована над инвариантом: переход состояния выполняет только владелец,
# и текст отказа у block и complete совпадает.
tid3="$(brain-task add "Открытая под локом для block" --role developer 2>&1 | tail -1 | sed 's/added: //')"
[ -n "$tid3" ] || { echo "FAILED: третья задача не создана"; exit 1; }
brain-lock acquire "$tid3" --as me --ttl 600 >/dev/null || { echo "FAILED: acquire на открытой задаче"; exit 1; }
grep -q -- "- \[ \].*$tid3 —" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: задача должна остаться open"; exit 1; }

cp "$BRAIN_PATH/tasks/active.md" "$snapshot_dir/active.block.before"
cp "$BRAIN_PATH/tasks/done.md" "$snapshot_dir/done.block.before"
cp "$BRAIN_PATH/wiki/log.md" "$snapshot_dir/log.block.before"
cp "$BRAIN_PATH/.locks/$tid3/owner" "$snapshot_dir/owner.block.before"

set +e
block_out="$(brain-task block "$tid3" "need info" --as intruder 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: чужой block выбил открытую задачу под локом"; exit 1; }
grep -q "lock owned by me, not intruder" <<< "$block_out" || {
  echo "FAILED: open-task block error unclear: $block_out"; exit 1;
}
cmp -s "$snapshot_dir/active.block.before" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: intruder block changed active.md"; exit 1; }
cmp -s "$snapshot_dir/done.block.before" "$BRAIN_PATH/tasks/done.md" || { echo "FAILED: intruder block changed done.md"; exit 1; }
cmp -s "$snapshot_dir/log.block.before" "$BRAIN_PATH/wiki/log.md" || { echo "FAILED: intruder block changed wiki/log.md"; exit 1; }
cmp -s "$snapshot_dir/owner.block.before" "$BRAIN_PATH/.locks/$tid3/owner" || { echo "FAILED: intruder block changed lock owner"; exit 1; }
echo "OK: открытую задачу под локом чужой не блокирует"

# Отказ не зависит от глагола: block и complete на одной расстановке говорят одно.
set +e
complete_out="$(brain-task complete "$tid3" --as intruder --model evil-model-1 2>&1)"
set -e
grep -q "lock owned by me, not intruder" <<< "$complete_out" || {
  echo "FAILED: complete на той же расстановке отказал иначе: $complete_out"; exit 1;
}
echo "OK: block и complete отказывают одинаково"

# Протухший лок не держит block — как и acquire, и complete.
python3 - "$BRAIN_PATH/.locks/$tid3/owner" <<'PY'
from pathlib import Path
import sys, time
path = Path(sys.argv[1])
owner, _ts, ttl = path.read_text(encoding="utf-8").strip().split("|")
path.write_text(f"{owner}|{int(time.time())-1000}|{ttl}\n", encoding="utf-8")
PY
brain-task block "$tid3" "stale lock does not hold" --as passerby >/dev/null || {
  echo "FAILED: протухший лок не пустил block"; exit 1;
}
grep -q -- "- \[!\].*$tid3 —" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: задача не помечена [!]"; exit 1; }
echo "OK: протухший лок не держит block"

echo ">>> queue idempotency checks passed"
