#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-compact-adapters dry-run is side-effect free"
adapter_dir="$BRAIN_PATH/.agent-configs/compact-adapters"
brain-compact-adapters dry-run --provider all > /tmp/brain_adapters_dryrun.txt
grep -q "dry-run has no side effects" /tmp/brain_adapters_dryrun.txt || { echo "FAILED: dry-run missing opt-in contract"; exit 1; }
grep -q "rollback: brain-compact-adapters uninstall" /tmp/brain_adapters_dryrun.txt || { echo "FAILED: dry-run missing rollback"; exit 1; }
[ ! -e "$adapter_dir" ] || { echo "FAILED: dry-run created adapter dir"; exit 1; }

echo ">>> Verifying brain-compact-adapters install/uninstall"
brain-compact-adapters install --provider all > /tmp/brain_adapters_install.txt
[ -f "$adapter_dir/claude-settings.brain-compact.json" ] || { echo "FAILED: Claude adapter missing"; exit 1; }
[ -f "$adapter_dir/AGENTS.brain-compact.md" ] || { echo "FAILED: Codex adapter missing"; exit 1; }
[ -f "$adapter_dir/GEMINI.brain-compact.md" ] || { echo "FAILED: Gemini adapter missing"; exit 1; }
grep -q "no global Claude/Codex/Gemini config is modified" /tmp/brain_adapters_install.txt || { echo "FAILED: install missing no-global-config contract"; exit 1; }
grep -q "brain-compact --kind test" "$adapter_dir/AGENTS.brain-compact.md" || { echo "FAILED: Codex adapter missing compact command"; exit 1; }
grep -q "Rollback" "$adapter_dir/GEMINI.brain-compact.md" || { echo "FAILED: Gemini adapter missing rollback"; exit 1; }

brain-compact-adapters uninstall --provider all > /tmp/brain_adapters_uninstall.txt
[ ! -e "$adapter_dir" ] || { echo "FAILED: uninstall left adapter dir"; exit 1; }

echo "brain-compact-adapters OK"
