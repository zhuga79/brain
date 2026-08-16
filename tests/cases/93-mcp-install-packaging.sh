#!/usr/bin/env bash
# case: mcp-install-packaging — installer ships the canonical modular MCP tree
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying install-brain-mcp.sh packages the canonical modular MCP tree"

brain_factory
bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1
export BRAIN_SYSTEM_PATH="$PROJECT_ROOT"

MCP_DIR="$HOME/.local/share/brain-mcp"
mkdir -p "$MCP_DIR"
python3 -m venv "$MCP_DIR/.venv"

site_dir="$("$MCP_DIR/.venv/bin/python" - <<'PY'
import sysconfig
print(sysconfig.get_path("purelib"))
PY
)"

mkdir -p "$site_dir/mcp/server"
printf '' > "$site_dir/mcp/__init__.py"
printf '' > "$site_dir/mcp/server/__init__.py"
cat > "$site_dir/mcp/server/fastmcp.py" <<'PY'
class FastMCP:
    def __init__(self, name):
        self.name = name
        self._tools = []

    def tool(self):
        def decorator(func):
            self._tools.append(func)
            return func
        return decorator

    def resource(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator

    def run(self, *args, **kwargs):
        return None
PY

printf 'legacy\n' > "$MCP_DIR/server.py"
mkdir -p "$MCP_DIR/runtime/mcp"
printf 'stale\n' > "$MCP_DIR/runtime/mcp/stale.py"

env BRAIN_MCP_SKIP_PIP=1 bash "$PROJECT_ROOT/install-brain-mcp.sh" >/tmp/mcp-install.out 2>/tmp/mcp-install.err || {
  cat /tmp/mcp-install.out
  cat /tmp/mcp-install.err
  fail_case "install-brain-mcp.sh failed in offline test mode"
}

assert_file_exists "$MCP_DIR/manifest.json"
[ ! -f "$MCP_DIR/server.py" ] || fail_case "legacy top-level server.py survived reinstall"
[ ! -f "$MCP_DIR/runtime/mcp/stale.py" ] || fail_case "stale runtime file survived reinstall"
assert_file_exists "$MCP_DIR/runtime/mcp/server.py"
assert_file_exists "$MCP_DIR/runtime/mcp/common.py"
assert_file_exists "$MCP_DIR/runtime/mcp/tools_tasks.py"
assert_file_exists "$MCP_DIR/runtime/lib/brain_core/paths.py"

python3 "$PROJECT_ROOT/runtime/mcp/packaging.py" verify --system-root "$PROJECT_ROOT" --install-root "$MCP_DIR" >/tmp/mcp-verify.out || {
  cat /tmp/mcp-verify.out
  fail_case "installed MCP manifest drifted from source"
}

"$HOME/.local/bin/brain-mcp" --help >/tmp/mcp-help.out 2>/tmp/mcp-help.err || {
  cat /tmp/mcp-help.out
  cat /tmp/mcp-help.err
  fail_case "installed brain-mcp launcher --help failed"
}
grep -q "Brain MCP server" /tmp/mcp-help.out || fail_case "brain-mcp --help missing argparse output"

python3 - <<'PY'
import json
import os
from pathlib import Path

manifest = json.loads(Path(os.environ["HOME"]).joinpath(".local/share/brain-mcp/manifest.json").read_text())
assert manifest["file_count"] == len(manifest["files"]) > 10
assert "runtime/mcp/server.py" in manifest["files"]
assert "runtime/lib/brain_core/paths.py" in manifest["files"]
assert "runtime/lib/brain_core/prdfile.py" in manifest["files"]
print("manifest ok")
PY

cat > "$MCP_DIR/.venv/bin/pip" <<'EOF'
#!/usr/bin/env bash
echo "pip should not run for existing MCP refresh" >&2
exit 97
EOF
chmod +x "$MCP_DIR/.venv/bin/pip"
env -u BRAIN_MCP_SKIP_PIP bash "$PROJECT_ROOT/install-brain-mcp.sh" >/tmp/mcp-reinstall.out 2>/tmp/mcp-reinstall.err || {
  cat /tmp/mcp-reinstall.out
  cat /tmp/mcp-reinstall.err
  fail_case "existing MCP refresh unexpectedly depended on pip"
}

# После удачной установки служебных каталогов не остаётся.
leftovers="$(find "$MCP_DIR" -maxdepth 1 -name '.brain-mcp-*' -print)"
[ -z "$leftovers" ] || fail_case "install left temp/backup leftovers: $leftovers"

# -----------------------------------------------------------------------------
# Прерванная подмена восстановима
# -----------------------------------------------------------------------------
# Обрыв имитируем в самой опасной точке: прежнее дерево уже уехало в backup,
# новое ещё не внесено, журнал на месте. Без восстановления установка здесь
# остаётся без runtime/ — ровно то, чем был опасен старый install.
echo ">>> Verifying interrupted swap is recoverable"
crash_backup="$MCP_DIR/.brain-mcp-backup-crash"
crash_stage="$MCP_DIR/.brain-mcp-stage-crash"
mkdir -p "$crash_backup" "$crash_stage"
mv "$MCP_DIR/runtime" "$crash_backup/runtime"
cat > "$MCP_DIR/.brain-mcp-swap.json" <<'JSON'
{"backup": ".brain-mcp-backup-crash", "incoming": ["runtime", "manifest.json"], "replaced": ["manifest.json", "runtime"], "schema": "brain-mcp-swap-journal-v1", "stage": ".brain-mcp-stage-crash"}
JSON

python3 "$PROJECT_ROOT/runtime/mcp/packaging.py" recover --install-root "$MCP_DIR" >/tmp/mcp-recover.out || {
  cat /tmp/mcp-recover.out
  fail_case "packaging recover failed after simulated crash"
}
grep -q '"recovered": true' /tmp/mcp-recover.out || {
  cat /tmp/mcp-recover.out
  fail_case "recover did not report a rollback"
}
assert_file_exists "$MCP_DIR/runtime/mcp/server.py"
assert_file_exists "$MCP_DIR/runtime/lib/brain_core/paths.py"
[ ! -e "$crash_backup" ] || fail_case "backup tree survived recovery"
[ ! -e "$crash_stage" ] || fail_case "staging tree survived recovery"
[ ! -e "$MCP_DIR/.brain-mcp-swap.json" ] || fail_case "swap journal survived recovery"
python3 "$PROJECT_ROOT/runtime/mcp/packaging.py" verify --system-root "$PROJECT_ROOT" --install-root "$MCP_DIR" >/tmp/mcp-verify-recovered.out || {
  cat /tmp/mcp-verify-recovered.out
  fail_case "recovered MCP tree drifted from source"
}

# -----------------------------------------------------------------------------
# Установка отводится в сторону теми же переменными, что читает brain-status
# -----------------------------------------------------------------------------
echo ">>> Verifying installer honours BRAIN_MCP_DIR / BRAIN_MCP_LAUNCHER"
alt_dir="$HOME/alt-brain-mcp"
alt_launcher="$HOME/alt-bin/brain-mcp"
mkdir -p "$alt_dir"
ln -s "$MCP_DIR/.venv" "$alt_dir/.venv"
env BRAIN_MCP_DIR="$alt_dir" BRAIN_MCP_LAUNCHER="$alt_launcher" BRAIN_MCP_SKIP_PIP=1 \
  bash "$PROJECT_ROOT/install-brain-mcp.sh" >/tmp/mcp-alt.out 2>/tmp/mcp-alt.err || {
  cat /tmp/mcp-alt.out
  cat /tmp/mcp-alt.err
  fail_case "install-brain-mcp.sh ignored BRAIN_MCP_DIR"
}
assert_file_exists "$alt_dir/manifest.json"
assert_file_exists "$alt_dir/runtime/mcp/server.py"
assert_file_exists "$alt_launcher"
[ -L "$alt_dir/.venv" ] || fail_case "existing .venv was replaced by the refresh"
python3 "$PROJECT_ROOT/runtime/mcp/packaging.py" verify --system-root "$PROJECT_ROOT" --install-root "$alt_dir" >/dev/null || {
  fail_case "diverted MCP install drifted from source"
}
python3 "$PROJECT_ROOT/runtime/mcp/packaging.py" verify --system-root "$PROJECT_ROOT" --install-root "$MCP_DIR" >/dev/null || {
  fail_case "diverted install disturbed the default MCP tree"
}

echo ">>> MCP installer packaging checks passed"
