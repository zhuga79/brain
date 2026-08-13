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

# ── 5. Владелец снимает и повторяет ──
brain-task release "$tid" --as me >/dev/null || { echo "FAILED: release владельцем"; exit 1; }
brain-task release "$tid" --as me >/dev/null || { echo "FAILED: повторный release"; exit 1; }
echo "OK: release идемпотентен"

# ── 6. --force снимает чужой лок явно ──
brain-lock acquire "$tid" --as someone-else >/dev/null
brain-lock release "$tid" --force >/dev/null || { echo "FAILED: --force не сработал"; exit 1; }
[ "$(brain-lock status "$tid")" = "free" ] || { echo "FAILED: лок остался после --force"; exit 1; }
echo "OK: --force снимает чужой лок явно"

# ── 7. complete без --as не закрывает задачу ──
brain-task take "$tid" --as me >/dev/null
set +e
out="$(brain-task complete "$tid" 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: complete без --as прошёл"; exit 1; }
grep -q "укажи исполнителя" <<< "$out" || { echo "FAILED: непонятная причина отказа: $out"; exit 1; }
grep -q "$tid" "$BRAIN_PATH/tasks/active.md" || { echo "FAILED: задача закрыта без владельца"; exit 1; }
echo "OK: complete требует владельца"

BRAIN_AGENT_MODEL=probe-model brain-task complete "$tid" --as me >/dev/null || {
  echo "FAILED: complete владельцем"
  exit 1
}
grep -q "$tid" "$BRAIN_PATH/tasks/done.md" || { echo "FAILED: задача не попала в done"; exit 1; }
echo "OK: задача закрыта владельцем"

echo ">>> queue idempotency checks passed"
