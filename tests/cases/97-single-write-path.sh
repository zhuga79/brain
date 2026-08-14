#!/usr/bin/env bash
# case: single-write-path — commit of system files in the data repo is rejected
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying the data-repo write-path guard"

hook="$PROJECT_ROOT/runtime/hooks/pre-commit-write-path"
[ -x "$hook" ] || { echo "FAILED: missing executable $hook"; exit 1; }

brain_factory
td="$BRAIN_FACTORY_TMP"
data="$td/data"
system="$td/system"
mkdir -p "$data" "$system"

init_repo() {
  local root="$1"
  mkdir -p "$root"
  git -C "$root" init -q
  git -C "$root" config user.email "smoke@test.local"
  git -C "$root" config user.name "Smoke"
}

init_repo "$data"
init_repo "$system"

mkdir -p "$data/wiki" "$data/runtime/bin" "$system/runtime/bin"
printf '# wiki\n' > "$data/wiki/log.md"
printf '# data copy\n' > "$data/runtime/bin/brain-ops"
printf '# system copy\n' > "$system/runtime/bin/brain-ops"
git -C "$data" add wiki/log.md
git -C "$data" commit -q -m "data base"
git -C "$system" add runtime/bin/brain-ops
git -C "$system" commit -q -m "system base"

export BRAIN_PATH="$data"
export BRAIN="$data"
export BRAIN_SYSTEM_PATH="$system"
export GIT_DIR="$data/.git"
export GIT_WORK_TREE="$data"

# ── 1. Staged runtime/ in the data repo is rejected with a public-checkout hint
git -C "$data" add runtime/bin/brain-ops
set +e
out="$("$hook" 2>&1)"
rc=$?
set -e
unset GIT_DIR GIT_WORK_TREE
[ "$rc" -ne 0 ] || { echo "FAILED: hook allowed runtime/ commit in data repo"; echo "$out"; exit 1; }
printf '%s\n' "$out" | grep -q "runtime/bin/brain-ops" || {
  echo "FAILED: hook did not name the staged system file"; echo "$out"; exit 1
}
printf '%s\n' "$out" | grep -Eq "BRAIN_SYSTEM_PATH|системн" || {
  echo "FAILED: hook error is not clear"; echo "$out"; exit 1
}
printf '%s\n' "$out" | grep -Eq "git switch -c|ветк" || {
  echo "FAILED: hook did not point at a branch in the public checkout"; echo "$out"; exit 1
}
echo "OK: data-repo runtime/ commit rejected"

# ── 2. Data-layer commit in the data repo still passes
(
  export GIT_DIR="$data/.git" GIT_WORK_TREE="$data" BRAIN_PATH="$data" BRAIN_SYSTEM_PATH="$system"
  git -C "$data" reset -q HEAD -- runtime/bin/brain-ops
  printf '# more wiki\n' >> "$data/wiki/log.md"
  git -C "$data" add wiki/log.md
  "$hook"
)
echo "OK: data-layer commit in data repo passes"

# ── 3. The same runtime/ edit is allowed in the system checkout
(
  export GIT_DIR="$system/.git" GIT_WORK_TREE="$system" BRAIN_PATH="$data" BRAIN_SYSTEM_PATH="$system"
  printf '# edit in public checkout\n' >> "$system/runtime/bin/brain-ops"
  git -C "$system" add runtime/bin/brain-ops
  "$hook"
)
echo "OK: system-checkout runtime/ commit passes"

# ── 4. Legacy one-root does not block
legacy="$td/legacy"
init_repo "$legacy"
mkdir -p "$legacy/runtime/bin"
printf '# legacy\n' > "$legacy/runtime/bin/brain-ops"
git -C "$legacy" add runtime/bin/brain-ops
(
  export GIT_DIR="$legacy/.git" GIT_WORK_TREE="$legacy"
  unset BRAIN_SYSTEM_PATH
  export BRAIN_PATH="$legacy"
  "$hook"
)
echo "OK: legacy single-root runtime/ commit passes"

# ── 5. install-hooks and setup wire the write-path guard
grep -q 'pre-commit-write-path' "$PROJECT_ROOT/install-hooks.sh" || {
  echo "FAILED: install-hooks.sh does not wire pre-commit-write-path"
  exit 1
}
grep -q 'pre-commit-write-path' "$PROJECT_ROOT/setup-brain-v2.sh" || {
  echo "FAILED: setup-brain-v2.sh does not install the data-repo write-path hook"
  exit 1
}
echo "OK: hook is wired from install-hooks and setup"

# ── 6. Documented edit path is a branch in the public checkout
readme="$PROJECT_ROOT/README.md"
contrib="$PROJECT_ROOT/CONTRIBUTING.md"
grep -q 'BRAIN_SYSTEM_PATH' "$readme" "$contrib" || {
  echo "FAILED: docs missing BRAIN_SYSTEM_PATH"
  exit 1
}
grep -Eiq 'ветк' "$readme" "$contrib" || {
  echo "FAILED: docs do not say the edit path is a branch"
  exit 1
}
grep -q 'brain-ops update' "$readme" "$contrib" || {
  echo "FAILED: docs missing brain-ops update"
  exit 1
}
grep -q 'tests/run.sh' "$readme" "$contrib" || {
  echo "FAILED: docs missing tests/run.sh"
  exit 1
}
echo "OK: docs name the public-checkout branch path"

# ── 7. brain-ops update still does pull + install + tests/run.sh
ops="$PROJECT_ROOT/runtime/bin/brain-ops"
[ -x "$ops" ] || { echo "FAILED: brain-ops missing"; exit 1; }
ops_src="$(cat "$ops")"
printf '%s\n' "$ops_src" | grep -q 'git .*pull' || {
  echo "FAILED: brain-ops update does not pull"; exit 1
}
printf '%s\n' "$ops_src" | grep -q 'setup-brain-v2.sh' || {
  echo "FAILED: brain-ops update does not install"; exit 1
}
printf '%s\n' "$ops_src" | grep -q 'tests/run.sh' || {
  echo "FAILED: brain-ops update does not run tests/run.sh"; exit 1
}
echo "OK: brain-ops update is pull + install + tests/run.sh"

# ── 8. validate reports the same staged violation
export BRAIN_PATH="$data"
export BRAIN="$data"
export BRAIN_SYSTEM_PATH="$system"
git -C "$data" add runtime/bin/brain-ops
set +e
val="$(python3 -c 'from brain_wiki.validators import validate_staged_write_path; from pathlib import Path; import os
issues = validate_staged_write_path(Path(os.environ["BRAIN_PATH"]))
print("\n".join(f"{i.severity} {i.path} {i.message}" for i in issues))
raise SystemExit(0 if not issues else 1)' 2>&1)"
val_rc=$?
set -e
[ "$val_rc" -ne 0 ] || { echo "FAILED: validate ignored staged runtime/ in data repo"; echo "$val"; exit 1; }
printf '%s\n' "$val" | grep -q "runtime/bin/brain-ops" || {
  echo "FAILED: validate did not name staged runtime/"; echo "$val"; exit 1
}
echo "OK: validate flags staged system paths in the data repo"

echo ">>> single-write-path checks passed"
