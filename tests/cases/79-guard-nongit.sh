#!/usr/bin/env bash
# case: guard-nongit — brain-guard не рапортует «чисто» там, где ничего не смотрел
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-guard fails closed on non-git trees"

guard="$PROJECT_ROOT/runtime/bin/brain-guard"
[ -x "$guard" ] || { echo "FAILED: brain-guard not executable"; exit 1; }

probe="$(mktemp -d)"
ALL_TMPDIRS+=("$probe")
# Образец собирается из частей: иначе сам файл теста содержал бы готовый
# паттерн и попадал бы в находки guard при проверке репозитория.
_label="И""НН"
_mail="probe@""example-mail.test"
printf '%s: 1234567890\nсвязь: %s\n' "$_label" "$_mail" > "$probe/leak.md"

# ── 1. Дерево без git с персональными данными: находка, а не «чисто» ──
set +e
out="$(python3 "$guard" tree --brain "$probe" --generic-only 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || {
    echo "FAILED: non-git tree with PII reported clean (rc=0)"
    echo "$out"
    exit 1
}
grep -q "ИНН" <<< "$out" || {
    echo "FAILED: PII not reported, got:"
    echo "$out"
    exit 1
}
echo "OK: non-git tree is scanned, PII found (rc=$rc)"

# ── 2. Режимы, требующие git, отказывают явно ──
for scope in staged history; do
    set +e
    out="$(python3 "$guard" "$scope" --brain "$probe" --generic-only 2>&1)"
    rc=$?
    set -e
    [ "$rc" -eq 2 ] || {
        echo "FAILED: '$scope' on a non-git tree returned $rc, expected 2"
        echo "$out"
        exit 1
    }
    grep -q "git-репозитор" <<< "$out" || {
        echo "FAILED: '$scope' gave no reason, got: $out"
        exit 1
    }
done
echo "OK: staged and history refuse without git"

# ── 3. Чистое дерево без git — по-прежнему успех ──
clean="$(mktemp -d)"
ALL_TMPDIRS+=("$clean")
printf '# заголовок\nобычный текст без данных\n' > "$clean/ok.md"
set +e
python3 "$guard" tree --brain "$clean" --generic-only >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -eq 0 ] || { echo "FAILED: clean non-git tree reported problems (rc=$rc)"; exit 1; }
echo "OK: clean non-git tree passes"

# ── 4. Без файла именных правил проверка отвергается ──
set +e
out="$(BRAIN_PUBLISH_SECRETS=/nonexistent python3 "$guard" tree --brain "$clean" 2>&1)"
rc=$?
set -e
[ "$rc" -eq 2 ] || {
    echo "FAILED: missing named rules did not fail closed (rc=$rc)"
    echo "$out"
    exit 1
}
echo "OK: missing named rules fail closed"

echo ">>> brain-guard fail-closed checks passed"
