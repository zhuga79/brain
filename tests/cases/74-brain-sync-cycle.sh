#!/usr/bin/env bash
# Smoke test for the LAN-safe Brain synchronizer cycle.
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-sync-cycle"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

repo="$BRAIN_FACTORY_TMP/repo"
mkdir -p "$repo/wiki" "$repo/tasks"
printf "# Test Brain\n" > "$repo/MEMORY.md"
printf "# Active Tasks\n" > "$repo/tasks/active.md"
printf "# Done Tasks\n\n" > "$repo/tasks/done.md"
printf "# Log\n" > "$repo/wiki/log.md"
mkdir -p "$repo/config"
printf '{"version": 2, "defaults": {"cli": "codex"}, "roles": {}}\n' > "$repo/config/routing.json"

git -C "$repo" init >/dev/null
git -C "$repo" config user.email "smoke@test.com"
git -C "$repo" config user.name "Smoke Test"
git -C "$repo" add .
git -C "$repo" commit -m "Initial Brain" >/dev/null

echo ">>> dry-run reports ready state"
python3 "$PROJECT_ROOT/runtime/bin/brain-sync-cycle" --brain "$repo" --repo "$repo" --dry-run --json > "$BRAIN_FACTORY_TMP/dry-run.json"
grep -q '"status": "ready"' "$BRAIN_FACTORY_TMP/dry-run.json" || {
  echo "FAILED: dry-run did not report ready"
  cat "$BRAIN_FACTORY_TMP/dry-run.json"
  exit 1
}
grep -q '"would_sync": true' "$BRAIN_FACTORY_TMP/dry-run.json" || {
  echo "FAILED: dry-run did not report would_sync"
  cat "$BRAIN_FACTORY_TMP/dry-run.json"
  exit 1
}

echo ">>> apply auto-commits journal-only dirt (wiki/log.md)"
printf -- "- 2026-07-07T00:00:00: provider-probe: OK\n" >> "$repo/wiki/log.md"
# без удалённого remote sync упадёт позже, но журнал должен закоммититься
python3 "$PROJECT_ROOT/runtime/bin/brain-sync-cycle" --brain "$repo" --repo "$repo" --apply --json > "$BRAIN_FACTORY_TMP/apply-journal.json" 2>&1 || true
grep -q '"journal_committed": true' "$BRAIN_FACTORY_TMP/apply-journal.json" || {
  echo "FAILED: journal-only dirt was not auto-committed"
  cat "$BRAIN_FACTORY_TMP/apply-journal.json"
  exit 1
}
if git -C "$repo" status --porcelain -- wiki/log.md | grep -q .; then
  echo "FAILED: wiki/log.md still dirty after auto-commit"
  exit 1
fi
git -C "$repo" log -1 --format=%s | grep -q "автозаписи журнала" || {
  echo "FAILED: auto-commit message missing"
  exit 1
}

echo ">>> apply refuses preflight-blocked runtime files"
printf '{}\n' > "$repo/.provider-health.json"
if python3 "$PROJECT_ROOT/runtime/bin/brain-sync-cycle" --brain "$repo" --repo "$repo" --apply --json > "$BRAIN_FACTORY_TMP/apply-blocked.json" 2>&1; then
  echo "FAILED: apply succeeded despite preflight block"
  cat "$BRAIN_FACTORY_TMP/apply-blocked.json"
  exit 1
fi
grep -q '"status": "blocked"' "$BRAIN_FACTORY_TMP/apply-blocked.json" || {
  echo "FAILED: blocked apply did not report blocked status"
  cat "$BRAIN_FACTORY_TMP/apply-blocked.json"
  exit 1
}
grep -q 'runtime-file-included' "$BRAIN_FACTORY_TMP/apply-blocked.json" || {
  echo "FAILED: blocked apply did not include runtime-file-included"
  cat "$BRAIN_FACTORY_TMP/apply-blocked.json"
  exit 1
}

echo ">>> install-systemd writes disabled user units"
unit_dir="$BRAIN_FACTORY_TMP/systemd-user"
python3 "$PROJECT_ROOT/runtime/bin/brain-sync-cycle" install-systemd --brain "$repo" --repo "$repo" --unit-dir "$unit_dir" --interval 7min --no-enable --json > "$BRAIN_FACTORY_TMP/install.json"
test -f "$unit_dir/brain-sync.service" || { echo "FAILED: service unit missing"; exit 1; }
test -f "$unit_dir/brain-sync.timer" || { echo "FAILED: timer unit missing"; exit 1; }
grep -q "ExecStart=.*brain-sync-cycle.*--apply" "$unit_dir/brain-sync.service" || {
  echo "FAILED: service does not run sync cycle apply"
  cat "$unit_dir/brain-sync.service"
  exit 1
}
grep -q "OnUnitActiveSec=7min" "$unit_dir/brain-sync.timer" || {
  echo "FAILED: timer interval not written"
  cat "$unit_dir/brain-sync.timer"
  exit 1
}

echo ">>> install-systemd supports named sync units"
python3 "$PROJECT_ROOT/runtime/bin/brain-sync-cycle" install-systemd --brain "$repo" --repo "$repo" --unit-dir "$unit_dir" --interval 11min --unit-name brain-sync-kvashnino --no-enable --json > "$BRAIN_FACTORY_TMP/install-named.json"
test -f "$unit_dir/brain-sync-kvashnino.service" || { echo "FAILED: named service unit missing"; exit 1; }
test -f "$unit_dir/brain-sync-kvashnino.timer" || { echo "FAILED: named timer unit missing"; exit 1; }
grep -q "ExecStart=.*brain-sync-cycle.*--no-rebuild-index" "$unit_dir/brain-sync-kvashnino.service" && {
  echo "FAILED: named default unit unexpectedly disabled index rebuild"
  cat "$unit_dir/brain-sync-kvashnino.service"
  exit 1
}
grep -q "OnUnitActiveSec=11min" "$unit_dir/brain-sync-kvashnino.timer" || {
  echo "FAILED: named timer interval not written"
  cat "$unit_dir/brain-sync-kvashnino.timer"
  exit 1
}

echo "brain-sync-cycle OK"
