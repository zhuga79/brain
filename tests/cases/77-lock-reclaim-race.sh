#!/usr/bin/env bash
# case: lock-reclaim-race — протухший лок достаётся ровно одному претенденту
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying stale-lock reclaim is atomic under concurrency"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

task="t-2026-01-01-reclaim-probe"
locks="$BRAIN_PATH/.locks"
mkdir -p "$locks/$task"

# Лок, протухший заведомо: возраст много больше ttl.
printf "dead-agent|%s|1\n" "$(( $(date +%s) - 9999 ))" > "$locks/$task/owner"

# Десять претендентов стартуют одновременно и пытаются перехватить его.
out_dir="$(mktemp -d)"
ALL_TMPDIRS+=("$out_dir")
for i in $(seq 1 10); do
    (
        # set +e обязателен: отказ в локе — это rc=1, и при set -e подоболочка
        # оборвалась бы, не записав код возврата.
        set +e
        brain-lock acquire "$task" --as "racer-$i" --ttl 600 \
            > "$out_dir/$i.out" 2>&1
        echo $? > "$out_dir/$i.rc"
    ) &
done
wait

ok_count=0
denied_count=0
for i in $(seq 1 10); do
    rc="$(cat "$out_dir/$i.rc" 2>/dev/null || echo 99)"
    if [ "$rc" = "0" ]; then
        ok_count=$((ok_count + 1))
    elif [ "$rc" = "1" ]; then
        denied_count=$((denied_count + 1))
    else
        echo "FAILED: racer-$i exited with unexpected code $rc"
        cat "$out_dir/$i.out"
        exit 1
    fi
done

[ "$ok_count" -eq 1 ] || {
    echo "FAILED: expected exactly one winner, got $ok_count"
    grep -l . "$out_dir"/*.out | while read -r f; do echo "  $(basename "$f"): $(cat "$f")"; done
    exit 1
}
[ "$denied_count" -eq 9 ] || {
    echo "FAILED: expected nine refusals, got $denied_count"
    exit 1
}
echo "OK: exactly one winner, nine refused"

# Владелец в файле — тот же, кто получил ok.
winner=""
for i in $(seq 1 10); do
    [ "$(cat "$out_dir/$i.rc")" = "0" ] && winner="racer-$i"
done
owner_agent="$(cut -d'|' -f1 < "$locks/$task/owner")"
[ "$owner_agent" = "$winner" ] || {
    echo "FAILED: owner file says '$owner_agent' but the winner was '$winner'"
    exit 1
}
echo "OK: owner file matches the winner"

# Свежий лок не перехватывается вовсе.
set +e
brain-lock acquire "$task" --as "latecomer" > "$out_dir/late.out" 2>&1
late_rc=$?
set -e
[ "$late_rc" -eq 1 ] || {
    echo "FAILED: a fresh lock was taken over (rc=$late_rc)"
    cat "$out_dir/late.out"
    exit 1
}
grep -q "locked by" "$out_dir/late.out" || {
    echo "FAILED: no 'locked by' message for a fresh lock"
    cat "$out_dir/late.out"
    exit 1
}
echo "OK: fresh lock is not reclaimed"

echo ">>> lock reclaim race checks passed"
