#!/usr/bin/env bash
# case: runner mutex — второй tests/run.sh обязан отказаться, а не молча
# делить /tmp/brain_* и порты с уже идущим прогоном.
#
# Общий ресурс (t-2026-08-16-smoke-suite-cannot-run-concurr): больше сотни
# фиксированных путей /tmp/brain_*.{json,log,out,err,txt,html} плюс
# исторические порты-константы. Раннер создаёт временный HOME, но эти пути
# живут вне него и общие для любого чекаута. Изолировать каждый — растущая
# цель; вместо ложных падений второй прогон отказывает с диагностикой.
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying tests/run.sh refuses a concurrent foreign run"

LOCK_FILE="/tmp/brain-smoke-run.lock"
RUNNER="$PROJECT_ROOT/tests/run.sh"

# Запускает второй tests/run.sh с дедлайном: при рабочем мьютексе отказ
# мгновенный; если лок обойден, дочерний процесс уходит в bootstrap —
# это и есть RED. Код 124 = дедлайн, не отказ раннера.
spawn_runner() {
    python3 -c '
import os, subprocess, sys

cmd = ["bash", os.environ["RUNNER"], "__no_such_case__"]
try:
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=8,
        env=os.environ,
    )
except subprocess.TimeoutExpired as exc:
    sys.stdout.write(exc.stdout or "")
    sys.stdout.write(exc.stderr or "")
    sys.exit(124)
sys.stdout.write(p.stdout)
sys.stdout.write(p.stderr)
sys.exit(p.returncode)
'
}

assert_refused() {
    local label="$1"
    local out="$2"
    local rc="$3"

    [ "$rc" -eq 3 ] || {
        echo "FAILED: $label: concurrent run.sh exit $rc, expected 3 (busy)"
        echo "$out" | tail -30
        exit 1
    }
    grep -q "ОТКАЗ" <<< "$out" || {
        echo "FAILED: $label: refusal has no ОТКАЗ"
        echo "$out" | tail -20
        exit 1
    }
    grep -q "$LOCK_FILE" <<< "$out" || {
        echo "FAILED: $label: refusal does not name $LOCK_FILE"
        echo "$out" | tail -20
        exit 1
    }
    grep -q "/tmp/brain_" <<< "$out" || {
        echo "FAILED: $label: refusal does not name the shared /tmp/brain_* resource"
        echo "$out" | tail -20
        exit 1
    }
    grep -q "\[bootstrap\]" <<< "$out" && {
        echo "FAILED: $label: concurrent run reached bootstrap despite the lock"
        echo "$out" | tail -20
        exit 1
    }
    echo "OK: $label"
}

# ── 1. Родительский прогон держит системный лок — второй отказывает ──
export RUNNER
set +e
out="$(spawn_runner)"
rc=$?
set -e
assert_refused "default lock" "$out" "$rc"

# ── 2. TMPDIR не переносит лок: /tmp/brain_* всегда под /tmp, не под TMPDIR ──
# Исторический баг WIP: RUN_LOCK_FILE="\${TMPDIR:-/tmp}/brain-smoke-run.lock"
# давал двум деревьям с разным TMPDIR разные лок-файлы при тех же /tmp/brain_*.
other_tmp="$(mktemp -d)"
set +e
out="$(TMPDIR="$other_tmp" spawn_runner)"
rc=$?
set -e
rm -rf "$other_tmp"
assert_refused "TMPDIR must not relocate the lock" "$out" "$rc"

# ── 3. Файл системного лока существует и занят (не пустышка после прошлого прогона) ──
[ -e "$LOCK_FILE" ] || {
    echo "FAILED: runner lock file missing: $LOCK_FILE"
    exit 1
}
# >> : не резать pid держателя. `exec 8>` до flock уничтожил бы содержимое
# даже при отказе в локе.
exec 8>>"$LOCK_FILE"
if flock -n 8; then
    exec 8>&-
    echo "FAILED: $LOCK_FILE is not held by the parent run"
    exit 1
fi
exec 8>&-
echo "OK: parent run holds $LOCK_FILE"

echo "smoke run isolation OK"
