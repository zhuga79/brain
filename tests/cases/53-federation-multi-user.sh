#!/usr/bin/env bash
# case: federation-multi-user — two vaults on a shared bare remote run a
# concurrent cycle; sync merges the queue (s4) and the journal (s3) with no
# loss, and preflight warns about a locally-locked task (s2).
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying multi-user federation cycle (queue + journal merge, lock warning)"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
git config --global init.defaultBranch master
FED="$PROJECT_ROOT/runtime/bin/brain-federation"

REMOTE="$BRAIN_FACTORY_TMP/remote.git"
git init -q --bare -b master "$REMOTE"

VA="$BRAIN_FACTORY_TMP/vault-a"
git clone -q "$REMOTE" "$VA"
git -C "$VA" config user.email a@node.test
git -C "$VA" config user.name node-a
git -C "$VA" config commit.gpgsign false
mkdir -p "$VA/tasks" "$VA/wiki" "$VA/.locks"
printf '.locks/\n' > "$VA/.gitignore"
cat > "$VA/tasks/active.md" <<'EOF'
# Active Tasks

- [ ] [P1] t-shared — Shared task both nodes see
      role: developer
      acceptance: ok

- [ ] [P1] t-a-owned — A picks this up
      role: developer
      acceptance: ok

- [ ] [P1] t-b-owned — B picks this up
      role: developer
      acceptance: ok
EOF
printf '# Done tasks\n' > "$VA/tasks/done.md"
printf '# Log\n' > "$VA/wiki/log.md"
git -C "$VA" add -A
git -C "$VA" commit -qm base
git -C "$VA" push -q origin master

VB="$BRAIN_FACTORY_TMP/vault-b"
git clone -q "$REMOTE" "$VB"
git -C "$VB" config user.email b@node.test
git -C "$VB" config user.name node-b
git -C "$VB" config commit.gpgsign false

# --- A: progress t-a-owned, add a task, log, push ---------------------------
cat > "$VA/tasks/active.md" <<'EOF'
# Active Tasks

- [ ] [P1] t-shared — Shared task both nodes see
      role: developer
      acceptance: ok

- [~] [P1] t-a-owned — A picks this up
      role: developer
      acceptance: ok
      started: 2026-09-02T09:00:00Z
      by: agent-a

- [ ] [P1] t-b-owned — B picks this up
      role: developer
      acceptance: ok

- [ ] [P1] t-a-new — Filed by A
      role: developer
      acceptance: ok
EOF
printf '## [2026-09-02T09:00:00Z] task-start | t-a-owned | agent-a | node=node-a\n' >> "$VA/wiki/log.md"
git -C "$VA" commit -aqm "a: take t-a-owned + file t-a-new"
git -C "$VA" push -q origin master

# --- B: progress t-b-owned, add a task, log, hold a lock on t-shared -------
mkdir -p "$VB/.locks/t-shared"
printf 'agent-b|%s|3600\n' "$(date +%s)" > "$VB/.locks/t-shared/owner"
cat > "$VB/tasks/active.md" <<'EOF'
# Active Tasks

- [ ] [P1] t-shared — Shared task both nodes see
      role: developer
      acceptance: ok

- [ ] [P1] t-a-owned — A picks this up
      role: developer
      acceptance: ok

- [~] [P1] t-b-owned — B picks this up
      role: developer
      acceptance: ok
      started: 2026-09-02T09:01:00Z
      by: agent-b

- [ ] [P1] t-b-new — Filed by B
      role: developer
      acceptance: ok
EOF
printf '## [2026-09-02T09:01:00Z] task-start | t-b-owned | agent-b | node=node-b\n' >> "$VB/wiki/log.md"

# --- s2: preflight (run against the in-flight working tree, before B commits)
#         warns that a locally-held lock covers a task whose files changed ----
BRAIN_NODE_ID=node-b python3 "$FED" preflight --repo "$VB" --brain "$VB" --json > "$BRAIN_FACTORY_TMP/preflight-b.json" || true
grep -q "federated-lock-warning" "$BRAIN_FACTORY_TMP/preflight-b.json" \
  || { echo "FAILED: preflight did not warn about the held lock"; cat "$BRAIN_FACTORY_TMP/preflight-b.json"; exit 1; }
grep -q "t-shared is locked locally" "$BRAIN_FACTORY_TMP/preflight-b.json" \
  || { echo "FAILED: lock warning did not name t-shared"; cat "$BRAIN_FACTORY_TMP/preflight-b.json"; exit 1; }
# a gitignored .locks/ that only exists on disk must not block preflight
grep -q '"runtime-file-included"' "$BRAIN_FACTORY_TMP/preflight-b.json" \
  && { echo "FAILED: gitignored .locks/ tripped runtime-file-included"; cat "$BRAIN_FACTORY_TMP/preflight-b.json"; exit 1; }
grep -q '"ok": true' "$BRAIN_FACTORY_TMP/preflight-b.json" \
  || { echo "FAILED: preflight not ok for a normal vault with a held lock"; cat "$BRAIN_FACTORY_TMP/preflight-b.json"; exit 1; }
echo "OK: preflight surfaces the federated lock conflict without a false block (s2)"

git -C "$VB" commit -aqm "b: take t-b-owned + file t-b-new"

# --- B syncs: rebase conflict on active.md + log.md, both auto-merged -----
BRAIN_NODE_ID=node-b python3 "$FED" sync --repo "$VB" --brain "$VB" > "$BRAIN_FACTORY_TMP/sync-b.out" 2>&1 \
  || { echo "FAILED: B sync did not converge"; cat "$BRAIN_FACTORY_TMP/sync-b.out"; exit 1; }

b_active="$VB/tasks/active.md"
b_log="$VB/wiki/log.md"
grep -q "<<<<<<<" "$b_active" "$b_log" && { echo "FAILED: conflict markers left in B's tree"; exit 1; }

# s4: no task lost, both nodes' new ids present, progressions kept
for tid in t-shared t-a-owned t-b-owned t-a-new t-b-new; do
  grep -qE "^- \[.\] \[P1\] $tid —" "$b_active" || { echo "FAILED: $tid missing from B's queue after merge"; cat "$b_active"; exit 1; }
done
grep -qE "^- \[~\] \[P1\] t-a-owned —" "$b_active" || { echo "FAILED: A's progression of t-a-owned lost"; exit 1; }
grep -qE "^- \[~\] \[P1\] t-b-owned —" "$b_active" || { echo "FAILED: B's own progression of t-b-owned lost"; exit 1; }
[ "$(grep -cE "^- \[.\] \[P1\] t-shared —" "$b_active")" = "1" ] || { echo "FAILED: t-shared duplicated"; exit 1; }
echo "OK: queue merged without loss (s4)"

# s3: journal has both nodes' rows, each once, timestamp-ordered
grep -q "task-start | t-a-owned | agent-a | node=node-a" "$b_log" || { echo "FAILED: A's log row lost"; cat "$b_log"; exit 1; }
grep -q "task-start | t-b-owned | agent-b | node=node-b" "$b_log" || { echo "FAILED: B's log row lost"; exit 1; }
[ "$(grep -c "task-start | t-a-owned | agent-a" "$b_log")" = "1" ] || { echo "FAILED: A's log row duplicated"; exit 1; }
# ordering is asserted over the merge-driver rows only; brain-federation
# appends a local, unpushed "federation-sync" status line after the rebase.
ts_order="$(grep 'task-start' "$b_log" | grep -oE '\[2026-[0-9T:-]+Z\]')"
first_ts="$(printf '%s\n' "$ts_order" | head -1)"
last_ts="$(printf '%s\n' "$ts_order" | tail -1)"
[ "$first_ts" = "[2026-09-02T09:00:00Z]" ] && [ "$last_ts" = "[2026-09-02T09:01:00Z]" ] \
  || { echo "FAILED: journal not timestamp-ordered ($first_ts .. $last_ts)"; cat "$b_log"; exit 1; }
echo "OK: journal merged with dedup and ordering (s3)"

# --- counter-sync: A pulls B's merged result, the vaults converge ---------
BRAIN_NODE_ID=node-a python3 "$FED" sync --repo "$VA" --brain "$VA" > "$BRAIN_FACTORY_TMP/sync-a.out" 2>&1 \
  || { echo "FAILED: A counter-sync did not converge"; cat "$BRAIN_FACTORY_TMP/sync-a.out"; exit 1; }
diff <(git -C "$VA" show HEAD:tasks/active.md) <(git -C "$VB" show HEAD:tasks/active.md) \
  || { echo "FAILED: vaults did not converge on active.md"; exit 1; }
diff <(git -C "$VA" show HEAD:wiki/log.md) <(git -C "$VB" show HEAD:wiki/log.md) \
  || { echo "FAILED: vaults did not converge on wiki/log.md"; exit 1; }
echo "OK: counter-sync converges both vaults"

# --- a real disagreement blocks instead of silently picking a side ------
git -C "$VB" pull -q --rebase >/dev/null 2>&1 || true
sed -i 's/t-shared — Shared task both nodes see/t-shared — Retitled by B/' "$VB/tasks/active.md"
git -C "$VB" commit -aqm "b: retitle t-shared"
sed -i 's/t-shared — Shared task both nodes see/t-shared — Retitled by A/' "$VA/tasks/active.md"
git -C "$VA" commit -aqm "a: retitle t-shared"
git -C "$VA" push -q origin master
set +e
BRAIN_NODE_ID=node-b python3 "$FED" sync --repo "$VB" --brain "$VB" --json > "$BRAIN_FACTORY_TMP/sync-b2.json" 2>&1
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: divergent retitle did not block the sync"; cat "$BRAIN_FACTORY_TMP/sync-b2.json"; exit 1; }
grep -q "federation-sync-queue-conflict" "$BRAIN_FACTORY_TMP/sync-b2.json" || { echo "FAILED: no queue-conflict finding"; cat "$BRAIN_FACTORY_TMP/sync-b2.json"; exit 1; }
[ -z "$(git -C "$VB" status --porcelain -- tasks/active.md)" ] || { echo "FAILED: blocked sync left tasks/active.md dirty"; exit 1; }
echo "OK: divergent field edit blocks the sync and aborts the rebase"

echo "multi-user federation cycle OK"
