#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-federation sync"

brain_factory
git config --global user.email "smoke@test.com"
git config --global user.name "Smoke Test"
git config --global init.defaultBranch master

# 1. Setup mock remote and local clones
REMOTE_REPO="$BRAIN_FACTORY_TMP/remote.git"
git init --bare "$REMOTE_REPO" >/dev/null

LOCAL_REPO1="$BRAIN_FACTORY_TMP/local1"
git clone "$REMOTE_REPO" "$LOCAL_REPO1" >/dev/null
cd "$LOCAL_REPO1"
touch initial.txt
git add initial.txt
git commit -m "Initial commit" >/dev/null
git push origin master >/dev/null

LOCAL_REPO2="$BRAIN_FACTORY_TMP/local2"
git clone "$REMOTE_REPO" "$LOCAL_REPO2" >/dev/null

# 2. Make change in local1 and push
cd "$LOCAL_REPO1"
echo "change from local1" > initial.txt
git commit -am "Update from local1" >/dev/null
git push origin master >/dev/null

# 3. Make change in local2 (no push yet)
cd "$LOCAL_REPO2"
echo "change from local2" > local2.txt
git add local2.txt
git commit -m "Update from local2" >/dev/null

# 4. Run brain-federation sync in local2
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
python3 "$PROJECT_ROOT/runtime/bin/brain-federation" sync --repo "$LOCAL_REPO2" >/dev/null

# 5. Verify sync result
cd "$LOCAL_REPO2"
[ -f initial.txt ] && grep -q "change from local1" initial.txt || { echo "FAILED: local2 did not receive update from local1"; exit 1; }
git log -n 1 | grep -q "Update from local2" || { echo "FAILED: local2 lost its own commit"; exit 1; }

# Verify local1 can now pull local2's change
cd "$LOCAL_REPO1"
git pull origin master >/dev/null
[ -f local2.txt ] || { echo "FAILED: remote did not receive push from local2 sync"; exit 1; }

echo "brain-federation sync OK"
