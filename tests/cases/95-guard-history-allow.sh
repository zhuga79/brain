#!/usr/bin/env bash
# case: guard-history-allow — scan_history уважает те же ALLOW, что и дерево
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying history scan applies the same ALLOW rules as tree"

guard="$PROJECT_ROOT/runtime/bin/brain-guard"
[ -x "$guard" ] || { echo "FAILED: brain-guard not executable"; exit 1; }

_init_repo() {
    local root="$1"
    git -C "$root" init --quiet
    git -C "$root" config user.email "you@example.com"
    git -C "$root" config user.name "guard-history-allow"
}

# ── 1. История только с ALLOW-адресами: как дерево, должна быть чистой ──
allow_repo="$(mktemp -d)"
ALL_TMPDIRS+=("$allow_repo")
_init_repo "$allow_repo"
# Фикстуры тестов: те же адреса, на которых краснел public master после squash.
cat > "$allow_repo/fixtures.md" <<'EOF'
contact: you@example.com
alt: t@t.com
from: smoke@local.test
noreply: noreply@localhost
autosave: autosave@brain.local
ci: runner@build.invalid
doc: someone@service.example
EOF
git -C "$allow_repo" add fixtures.md
git -C "$allow_repo" commit --quiet -m "fixture emails"

set +e
out="$(python3 "$guard" tree --brain "$allow_repo" --generic-only 2>&1)"
rc=$?
set -e
[ "$rc" -eq 0 ] || {
    echo "FAILED: tree should be clean on ALLOW fixture emails (rc=$rc)"
    echo "$out"
    exit 1
}

set +e
out="$(python3 "$guard" history --brain "$allow_repo" --generic-only 2>&1)"
rc=$?
set -e
[ "$rc" -eq 0 ] || {
    echo "FAILED: history should apply ALLOW and stay clean (rc=$rc)"
    echo "$out"
    exit 1
}
echo "OK: history --generic-only is clean on ALLOW fixture emails"

# ── 2. Реальный адрес вне ALLOW по-прежнему валит историю ──
# Собирается из частей, чтобы сам файл кейса не попадал в находки tree.
leak_repo="$(mktemp -d)"
ALL_TMPDIRS+=("$leak_repo")
_init_repo "$leak_repo"
_user="victim"
_dom="contoso.io"
printf 'contact: %s@%s\n' "$_user" "$_dom" > "$leak_repo/leak.md"
git -C "$leak_repo" add leak.md
git -C "$leak_repo" commit --quiet -m "real address"

set +e
out="$(python3 "$guard" history --brain "$leak_repo" --generic-only 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || {
    echo "FAILED: history stayed clean on a real address outside ALLOW"
    echo "$out"
    exit 1
}
grep -q "адрес почты" <<< "$out" || {
    echo "FAILED: real address was not reported as email, got:"
    echo "$out"
    exit 1
}
echo "OK: real address outside ALLOW still fails history"

# ── 3. Тот же реальный адрес валит и дерево — правила совпадают ──
set +e
out="$(python3 "$guard" tree --brain "$leak_repo" --generic-only 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || {
    echo "FAILED: tree stayed clean on a real address outside ALLOW"
    echo "$out"
    exit 1
}
echo "OK: tree and history agree on a real address"

echo ">>> history ALLOW checks passed"
