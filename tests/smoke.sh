#!/usr/bin/env bash
# tests/smoke.sh — Smoke test entry point for the Brain shell project
#
# Backward-compatible entry point. Delegates to tests/run.sh which
# runs individual case files from tests/cases/.
#
# Usage:
#   bash tests/smoke.sh              # run all cases
#   bash tests/smoke.sh phase6       # run cases matching "phase6"
#   bash tests/run.sh                # same as above (direct runner)

set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

echo ">>> Starting smoke test suite"
exec bash "$SCRIPT_DIR/run.sh" "${1:-}"
