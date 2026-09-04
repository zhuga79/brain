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

# The smoke suite never pulls container images itself — the real run is the
# deb-install CI job. Exercise the harness's SKIP path only.
out="$(BRAIN_SKIP_DEB_CONTAINER_TEST=1 bash "$script" 2>&1 || true)"
echo "$out" | grep -q '^SKIP:' \
  || { echo "FAILED: harness did not honour BRAIN_SKIP_DEB_CONTAINER_TEST: $out"; exit 1; }

echo "deb-install-verify OK (harness wired into CI; containers run there)"
