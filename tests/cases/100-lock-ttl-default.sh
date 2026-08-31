#!/usr/bin/env bash
# case: lock-ttl-default — default lease covers agent work; expiry still frees
# t-2026-08-14-lock-ttl-versus-agent-task-dur
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying lock TTL default and owner complete after expiry"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1

# ── 1. acquire без --ttl пишет 3600 ──
brain-lock acquire t-ttl-default --as agent-a >/dev/null
ttl="$(cut -d'|' -f3 "$BRAIN_PATH/.locks/t-ttl-default/owner")"
[ "$ttl" = "3600" ] || { echo "FAILED: default ttl is $ttl, expected 3600"; exit 1; }
brain-lock release t-ttl-default --as agent-a >/dev/null
echo "OK: default TTL is 3600s"

# ── 2. Владелец закрывает свою задачу после expiry ──
tid="$(brain-task add "Lock TTL owner complete" --role developer 2>&1 | tail -1 | sed 's/added: //')"
[ -n "$tid" ] || { echo "FAILED: задача не создана"; exit 1; }
brain-task take "$tid" --as owner-agent >/dev/null
owner_file="$BRAIN_PATH/.locks/$tid/owner"
printf 'owner-agent|1|1\n' > "$owner_file"
BRAIN_AGENT_MODEL=grok-4.6 brain-task complete "$tid" --as owner-agent >/dev/null \
  || { echo "FAILED: owner complete after TTL expiry"; exit 1; }
grep -q "$tid" "$BRAIN_PATH/tasks/done.md" || { echo "FAILED: задача не в done.md"; exit 1; }
grep -q "$tid" "$BRAIN_PATH/tasks/active.md" && { echo "FAILED: задача осталась в active.md"; exit 1; }
echo "OK: owner complete after expiry"

# ── 3. Протухший лок по-прежнему перехватывается ──
brain-lock acquire t-stale-takeover --as dead-agent --ttl 1 >/dev/null
sleep 2
out="$(brain-lock acquire t-stale-takeover --as next-agent --ttl 60 2>&1)"
grep -qi "ok" <<< "$out" || { echo "FAILED: stale takeover: $out"; exit 1; }
grep -q "^next-agent|" "$BRAIN_PATH/.locks/t-stale-takeover/owner" \
  || { echo "FAILED: owner file not taken over"; exit 1; }
brain-lock release t-stale-takeover --as next-agent >/dev/null
echo "OK: stale takeover still works"

# ── 4. cleanup снимает протухшие локи ──
brain-lock acquire t-stale-cleanup --as dead-agent --ttl 1 >/dev/null
sleep 2
out="$(brain-lock cleanup 2>&1)"
grep -Eq "cleaned [1-9]" <<< "$out" || { echo "FAILED: cleanup: $out"; exit 1; }
[ ! -d "$BRAIN_PATH/.locks/t-stale-cleanup" ] || { echo "FAILED: stale lock survived cleanup"; exit 1; }
echo "OK: cleanup still frees abandoned locks"

echo ">>> lock TTL default checks passed"
