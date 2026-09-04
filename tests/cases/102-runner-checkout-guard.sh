#!/usr/bin/env bash
# case: runner-checkout-guard — a case that writes into the project checkout is
# FAILED by the runner (t-2026-09-02-wiki-log-md), but python bytecode / tool
# caches that appear as the suite imports modules are not "pollution"
# (t-2026-09-04-ci-guard-pycache-brain-guard-p — they turned CI red).
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying the runner's checkout-pollution guard"

work="$(mktemp -d)"
ALL_TMPDIRS+=("$work")
guard_root="$work/checkout"
stub_cases="$work/cases"
mkdir -p "$guard_root" "$stub_cases"

git -C "$guard_root" init -q
git -C "$guard_root" config user.email t@test.local
git -C "$guard_root" config user.name t
printf 'tracked\n' > "$guard_root/keep.md"
mkdir -p "$guard_root/pkg"
printf 'mod\n' > "$guard_root/pkg/mod.py"   # a tracked dir; __pycache__ lands inside it
git -C "$guard_root" add -A
git -C "$guard_root" commit -qm base

cat > "$stub_cases/10-clean.sh" <<'EOF'
#!/usr/bin/env bash
echo "clean stub — touches nothing in the checkout"
EOF

cat > "$stub_cases/20-writes-into-checkout.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'oops\n' > "$PROJECT_ROOT/pollute.md"
echo "wrote a file into the checkout"
EOF

cat > "$stub_cases/30-only-bytecode.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$PROJECT_ROOT/pkg/__pycache__" "$PROJECT_ROOT/.pytest_cache" "$PROJECT_ROOT/.ruff_cache"
printf '\0' > "$PROJECT_ROOT/pkg/__pycache__/mod.cpython-312.pyc"
: > "$PROJECT_ROOT/.pytest_cache/CACHEDIR.TAG"
: > "$PROJECT_ROOT/.ruff_cache/.gitignore"
echo "created only python bytecode / tool caches"
EOF
chmod +x "$stub_cases"/*.sh

out="$work/nested.out"
set +e
BRAIN_SMOKE_PROJECT_ROOT="$guard_root" \
BRAIN_SMOKE_CASES_DIR="$stub_cases" \
BRAIN_SMOKE_SKIP_BOOTSTRAP=1 \
BRAIN_SMOKE_CASE_TIMEOUT=30 \
BRAIN_SMOKE_RUN_LOCK="$work/nested-run.lock" \
  bash "$PROJECT_ROOT/tests/run.sh" > "$out" 2>&1
nested_rc=$?
set -e

[ "$nested_rc" -ne 0 ] || { echo "FAILED: nested runner exited 0 despite a polluting case"; cat "$out"; exit 1; }

grep -Eq '\[case: 10-clean\] PASSED' "$out" \
  || { echo "FAILED: clean stub not PASSED"; cat "$out"; exit 1; }
grep -Eq '\[case: 20-writes-into-checkout\] FAILED \(wrote into the checkout' "$out" \
  || { echo "FAILED: polluting case not flagged"; cat "$out"; exit 1; }
grep -Eq '^ +\?\? pollute\.md' "$out" \
  || { echo "FAILED: guard did not name pollute.md"; cat "$out"; exit 1; }
grep -Eq '\[case: 30-only-bytecode\] PASSED' "$out" \
  || { echo "FAILED: bytecode-only case was flagged as pollution"; cat "$out"; exit 1; }
grep -Eq 'Results: 2 passed, 1 failed' "$out" \
  || { echo "FAILED: summary did not count exactly one pollution failure"; cat "$out"; exit 1; }

echo "runner-checkout-guard OK"
