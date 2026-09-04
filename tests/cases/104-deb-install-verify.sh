#!/usr/bin/env bash
# case: deb-install-verify — the container install harness is present, wired
# into CI, and its no-docker path is a clean SKIP (federation PRD s7).
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying tests/packaging/verify-deb-install.sh"

script="$PROJECT_ROOT/tests/packaging/verify-deb-install.sh"
[ -x "$script" ] || { echo "FAILED: $script missing or not executable"; exit 1; }
bash -n "$script" || { echo "FAILED: verify-deb-install.sh has a syntax error"; exit 1; }

# The CI workflow must run it as a blocking job.
wf="$PROJECT_ROOT/.github/workflows/tests.yml"
grep -q 'verify-deb-install.sh' "$wf" || { echo "FAILED: no CI job runs verify-deb-install.sh"; exit 1; }
grep -qE '^\s*deb-install:' "$wf" || { echo "FAILED: deb-install job missing from tests.yml"; exit 1; }

# Without docker the harness SKIPs cleanly so the smoke runner can call it.
out="$(bash "$script" 2>&1 || true)"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "$out" | grep -qE 'deb install verified on|FAILED' \
    || { echo "FAILED: docker present but harness produced no verdict"; echo "$out"; exit 1; }
  echo "$out" | grep -q 'FAILED' && { echo "FAILED: container install verification failed"; echo "$out"; exit 1; }
  echo "deb-install-verify OK (ran containers)"
else
  echo "$out" | grep -q '^SKIP:' || { echo "FAILED: no-docker run did not SKIP: $out"; exit 1; }
  echo "deb-install-verify OK (SKIP without docker; CI runs it for real)"
fi
