#!/usr/bin/env bash
# case: lock-status — brain-lock status не падает на пустом и на битом каталоге
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-lock status"

rm -rf "${BRAIN_PATH:?}/.locks"

# ── 1. Локов нет ──
# Пустой каталог не раскрывает шаблон, и в переменную попадает строка с «*».
# Раньше на этом status без аргументов падал арифметикой над «?».
out="$(brain-lock status 2>&1)"; rc=$?
[ "$rc" -eq 0 ] || { echo "FAILED: status без локов вернул $rc: $out"; exit 1; }
grep -q "no locks" <<< "$out" || { echo "FAILED: status без локов не сказал об этом: $out"; exit 1; }

out="$(brain-lock status --json 2>&1)"; rc=$?
[ "$rc" -eq 0 ] || { echo "FAILED: status --json без локов вернул $rc: $out"; exit 1; }
python3 -c "
import json, sys
d = json.loads(sys.argv[1])
assert d == {'locks': []}, d
" "$out" || { echo "FAILED: неверный JSON без локов: $out"; exit 1; }
echo "OK: пустой каталог локов"

# ── 2. Лок есть ──
brain-lock acquire t-status-probe --as probe-agent --ttl 60 >/dev/null
out="$(brain-lock status 2>&1)"
grep -q "t-status-probe" <<< "$out" || { echo "FAILED: лок не показан: $out"; exit 1; }
out="$(brain-lock status --json 2>&1)"
python3 -c "
import json, sys
d = json.loads(sys.argv[1])
assert [l['task_id'] for l in d['locks']] == ['t-status-probe'], d
assert d['locks'][0]['age_s'] >= 0, d
" "$out" || { echo "FAILED: неверный JSON с локом: $out"; exit 1; }
brain-lock release t-status-probe --as probe-agent >/dev/null
echo "OK: существующий лок виден"

# ── 3. Битый файл владельца ──
# Лок всё равно надо показать: иначе оператор не узнает, что он есть.
mkdir -p "$BRAIN_PATH/.locks/t-broken"
printf 'мусор\n' > "$BRAIN_PATH/.locks/t-broken/owner"
out="$(brain-lock status 2>&1)"; rc=$?
[ "$rc" -eq 0 ] || { echo "FAILED: битый owner уронил status ($rc): $out"; exit 1; }
grep -q "t-broken" <<< "$out" || { echo "FAILED: битый лок скрыт: $out"; exit 1; }
rm -rf "$BRAIN_PATH/.locks/t-broken"
echo "OK: битый файл владельца не роняет вывод"

echo ">>> brain-lock status checks passed"
