#!/usr/bin/env bash
set -euo pipefail

if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
# shellcheck disable=SC1091
source "$PROJECT_ROOT/tests/_lib.sh"

echo ">>> Verifying brain-index-refresh"

brain_factory
mkdir -p "$BRAIN_PATH/wiki"
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

# --- Test Case 1: Index is fresh, --apply mode ---
echo ">>> [1] Testing fresh index with --apply"
mkdir -p "$BRAIN_FACTORY_TMP/bin"
cat > "$BRAIN_FACTORY_TMP/bin/brain-index" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "stale" ]]; then
    echo "status: fresh"
    exit 0
fi
echo "ERROR: Unexpected call to brain-index with args: $@" >&2
exit 99
EOF
chmod +x "$BRAIN_FACTORY_TMP/bin/brain-index"
export PATH="$BRAIN_FACTORY_TMP/bin:$PATH"

brain-index-refresh --apply --json > "$BRAIN_FACTORY_TMP/fresh-apply.json"

if ! grep -q '"status": "success"' "$BRAIN_FACTORY_TMP/fresh-apply.json"; then
  echo "FAILED: Expected status 'success' on fresh index."
  cat "$BRAIN_FACTORY_TMP/fresh-apply.json"
  exit 1
fi
if ! grep -q "index-refresh: fresh" "$BRAIN_PATH/wiki/log.md"; then
  echo "FAILED: Log entry for fresh index was not written."
  cat "$BRAIN_PATH/wiki/log.md"
  exit 1
fi
echo "    Fresh index --apply OK"


# --- Test Case 2: Index is stale, --apply mode ---
echo ">>> [2] Testing stale index with --apply"
cat > "$BRAIN_FACTORY_TMP/bin/brain-index" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "stale" ]]; then
    echo "status: stale"
    exit 1
elif [[ "$1" == "rebuild" ]]; then
    echo "OK: rebuilt index"
    exit 0
fi
echo "ERROR: Unexpected call to brain-index with args: $@" >&2
exit 99
EOF

brain-index-refresh --apply --json > "$BRAIN_FACTORY_TMP/stale-apply.json"

if ! grep -q '"status": "success"' "$BRAIN_FACTORY_TMP/stale-apply.json"; then
  echo "FAILED: Expected status 'success' on stale index rebuild."
  cat "$BRAIN_FACTORY_TMP/stale-apply.json"
  exit 1
fi
if ! grep -q "index-refresh: rebuilt" "$BRAIN_PATH/wiki/log.md"; then
  echo "FAILED: Log entry for rebuilt index was not written."
  cat "$BRAIN_PATH/wiki/log.md"
  exit 1
fi
echo "    Stale index --apply OK"


# --- Test Case 3: Index is stale, --dry-run mode ---
echo ">>> [3] Testing stale index with --dry-run"
# Same mock as above (stale exit 1), but we want to ensure rebuild is NOT called.
# To check this, we can have the mock fail if "rebuild" is passed.
cat > "$BRAIN_FACTORY_TMP/bin/brain-index" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "stale" ]]; then
    echo "status: stale"
    exit 1
fi
echo "ERROR: Unexpected call to brain-index with args: $@ in dry-run test" >&2
exit 98
EOF

log_before_dry_run=$(cat "$BRAIN_PATH/wiki/log.md")

brain-index-refresh --dry-run --json > "$BRAIN_FACTORY_TMP/stale-dry-run.json"

if ! grep -q '"action": "would_rebuild"' "$BRAIN_FACTORY_TMP/stale-dry-run.json"; then
  echo "FAILED: Expected action 'would_rebuild' on stale dry-run."
  cat "$BRAIN_FACTORY_TMP/stale-dry-run.json"
  exit 1
fi
log_after_dry_run=$(cat "$BRAIN_PATH/wiki/log.md")
if [[ "$log_before_dry_run" != "$log_after_dry_run" ]]; then
    echo "FAILED: Log file was modified during --dry-run"
    diff <(echo "$log_before_dry_run") <(echo "$log_after_dry_run")
    exit 1
fi
echo "    Stale index --dry-run OK"


# --- Test Case 4: install-systemd ---
echo ">>> [4] Testing systemd installation"
unit_dir="$BRAIN_FACTORY_TMP/systemd"
brain-index-refresh install-systemd --unit-dir "$unit_dir" --no-enable

service_file="$unit_dir/brain-index-refresh.service"
timer_file="$unit_dir/brain-index-refresh.timer"

if [[ ! -f "$service_file" || ! -f "$timer_file" ]]; then
    echo "FAILED: systemd unit files not created."
    ls -l "$unit_dir"
    exit 1
fi

script_path=$(realpath "$PROJECT_ROOT/runtime/bin/brain-index-refresh")
if ! grep -q "ExecStart=" "$service_file" || ! grep -q "$script_path" "$service_file" || ! grep -q -- "--apply" "$service_file"; then
    echo "FAILED: Service file does not contain correct ExecStart."
    cat "$service_file"
    exit 1
fi

if ! grep -q "OnCalendar=daily" "$timer_file"; then
    echo "FAILED: Timer not set to daily."
    cat "$timer_file"
    exit 1
fi
echo "    Systemd installation OK"

echo
echo "brain-index-refresh test PASSED"
