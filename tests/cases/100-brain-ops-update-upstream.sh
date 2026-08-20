#!/usr/bin/env bash
# case: brain-ops-update-upstream — update fails with a diagnostic (not a raw
# git error) when the system checkout's branch has no upstream configured,
# names the fix command without guessing among several remotes, handles
# detached HEAD, and still works when upstream is set.
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-ops update upstream handling"

brain_factory
git config --global user.email "case@example.com"
git config --global user.name "case"
git config --global init.defaultBranch master

make_fake_system() {
  local dir="$1"
  mkdir -p "$dir/tests"
  cat > "$dir/setup-brain-v2.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$dir/setup-brain-v2.sh"
  cat > "$dir/tests/run.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$dir/tests/run.sh"
  git -C "$dir" init >/dev/null 2>&1
  echo one > "$dir/f"
  git -C "$dir" add -A >/dev/null 2>&1
  git -C "$dir" commit -q -m init
}

echo ">>> no remote at all: update fails, names how to add one"
sys_no_remote="$BRAIN_FACTORY_TMP/system-no-remote"
make_fake_system "$sys_no_remote"
set +e
out="$(BRAIN_SYSTEM_PATH="$sys_no_remote" bash "$PROJECT_ROOT/runtime/bin/brain-ops" update 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: update should fail without any remote"; echo "$out"; exit 1; }
echo "$out" | grep -q "has no upstream configured" || {
  echo "FAILED: missing no-upstream diagnostic"; echo "$out"; exit 1
}
echo "$out" | grep -q "remote add origin" || {
  echo "FAILED: no-remote diagnostic does not suggest adding one"; echo "$out"; exit 1
}
echo ">>> single remote, no upstream: update fails naming the exact fix command"
sys_single="$BRAIN_FACTORY_TMP/system-single-remote"
make_fake_system "$sys_single"
remote_single="$BRAIN_FACTORY_TMP/remote-single.git"
git init --bare "$remote_single" >/dev/null
git -C "$sys_single" remote add origin "$remote_single"
git -C "$sys_single" push -q origin master
set +e
out="$(BRAIN_SYSTEM_PATH="$sys_single" bash "$PROJECT_ROOT/runtime/bin/brain-ops" update 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: update should fail without upstream even with a remote present"; echo "$out"; exit 1; }
echo "$out" | grep -qF "git -C \"$sys_single\" branch --set-upstream-to=origin/master master" || {
  echo "FAILED: single-remote diagnostic does not name the exact fix command"; echo "$out"; exit 1
}

echo ">>> multiple remotes, no upstream: update refuses to guess"
sys_multi="$BRAIN_FACTORY_TMP/system-multi-remote"
make_fake_system "$sys_multi"
remote_a="$BRAIN_FACTORY_TMP/remote-a.git"
remote_b="$BRAIN_FACTORY_TMP/remote-b.git"
git init --bare "$remote_a" >/dev/null
git init --bare "$remote_b" >/dev/null
git -C "$sys_multi" remote add origin "$remote_a"
git -C "$sys_multi" remote add other "$remote_b"
git -C "$sys_multi" push -q origin master
set +e
out="$(BRAIN_SYSTEM_PATH="$sys_multi" bash "$PROJECT_ROOT/runtime/bin/brain-ops" update 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: update should fail rather than guess a remote"; echo "$out"; exit 1; }
echo "$out" | grep -q "<remote>/master" || {
  echo "FAILED: multi-remote diagnostic should not name a specific remote"; echo "$out"; exit 1
}
echo "$out" | grep -q "origin" && echo "$out" | grep -q "other" || {
  echo "FAILED: multi-remote diagnostic does not list configured remotes"; echo "$out"; exit 1
}

echo ">>> detached HEAD: update fails naming the checkout as the fix"
sys_detached="$BRAIN_FACTORY_TMP/system-detached"
make_fake_system "$sys_detached"
sha="$(git -C "$sys_detached" rev-parse HEAD)"
git -C "$sys_detached" checkout -q "$sha"
set +e
out="$(BRAIN_SYSTEM_PATH="$sys_detached" bash "$PROJECT_ROOT/runtime/bin/brain-ops" update 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: update should fail on a detached HEAD checkout"; echo "$out"; exit 1; }
echo "$out" | grep -q "detached HEAD" || {
  echo "FAILED: missing detached-HEAD diagnostic"; echo "$out"; exit 1
}
echo "$out" | grep -q "checkout <branch>" || {
  echo "FAILED: detached-HEAD diagnostic does not name the fix"; echo "$out"; exit 1
}

echo ">>> upstream configured: update still runs pull, install and tests"
sys_ok="$BRAIN_FACTORY_TMP/system-with-upstream"
make_fake_system "$sys_ok"
remote_ok="$BRAIN_FACTORY_TMP/remote-ok.git"
git init --bare "$remote_ok" >/dev/null
git -C "$sys_ok" remote add origin "$remote_ok"
git -C "$sys_ok" push -q -u origin master
out="$(BRAIN_SYSTEM_PATH="$sys_ok" bash "$PROJECT_ROOT/runtime/bin/brain-ops" update 2>&1)"
echo "$out" | grep -q "\[brain-ops\] pull" || {
  echo "FAILED: update with configured upstream did not reach pull"; echo "$out"; exit 1
}
echo "$out" | grep -q "\[brain-ops\] tests" || {
  echo "FAILED: update with configured upstream did not reach the test step"; echo "$out"; exit 1
}

echo "OK: brain-ops update handles missing/ambiguous upstream and detached HEAD, and still works when upstream is configured"
