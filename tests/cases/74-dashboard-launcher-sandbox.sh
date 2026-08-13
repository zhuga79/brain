#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying dashboard launcher refuses to start serve from Codex sandbox"

brain_factory

shim_dir="$(mktemp -d /tmp/brain-dashboard-launcher.XXXXXX)"
trap 'rm -rf "$shim_dir"' EXIT

cat > "$shim_dir/curl" <<'SH'
#!/usr/bin/env bash
exit 22
SH
cat > "$shim_dir/brain-dashboard" <<'SH'
#!/usr/bin/env bash
echo "brain-dashboard should not be started from sandbox" >&2
exit 77
SH
cat > "$shim_dir/xdg-open" <<'SH'
#!/usr/bin/env bash
echo "xdg-open should not be called from sandbox" >&2
exit 78
SH
chmod +x "$shim_dir/curl" "$shim_dir/brain-dashboard" "$shim_dir/xdg-open"

PATH="$shim_dir:$PROJECT_ROOT/runtime/bin:$PATH" \
  CODEX_SANDBOX_NETWORK_DISABLED=1 \
  "$PROJECT_ROOT/runtime/bin/launch-dashboard.sh" \
  >"$BRAIN_FACTORY_TMP/launcher.out" 2>"$BRAIN_FACTORY_TMP/launcher.err" && {
    echo "FAILED: sandboxed dashboard launcher returned success"
    exit 1
  }

grep -q "Refusing to start Brain Dashboard server from Codex sandbox" "$BRAIN_FACTORY_TMP/launcher.err" || {
  echo "FAILED: launcher did not explain sandbox refusal"
  cat "$BRAIN_FACTORY_TMP/launcher.err"
  exit 1
}
grep -q "brain-dashboard should not be started" "$BRAIN_FACTORY_TMP/launcher.err" && {
  echo "FAILED: launcher started dashboard despite sandbox refusal"
  cat "$BRAIN_FACTORY_TMP/launcher.err"
  exit 1
}

echo "dashboard launcher sandbox refusal OK"
