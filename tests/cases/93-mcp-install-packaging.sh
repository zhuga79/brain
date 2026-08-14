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

echo ">>> MCP installer packaging checks passed"
