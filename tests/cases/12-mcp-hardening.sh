#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-run tax-advisor pre-flight"
brain-run --role tax-advisor --task t-smoke-preflight 2>/dev/null | grep -q "PRE-FLIGHT\|ТЕКУЩИЙ ЭТАП" || { echo "FAILED: brain-run tax-advisor missing pre-flight block"; exit 1; }
brain-run --role developer --task t-smoke-preflight 2>/dev/null | grep -q "PRE-FLIGHT" && { echo "FAILED: brain-run developer should NOT have pre-flight block"; exit 1; } || true

echo ">>> Verifying brain-mcp --http hardening"
grep -q "def do_POST" "$PROJECT_ROOT/runtime/bin/brain-dashboard" || { echo "FAILED: do_POST missing from brain-dashboard"; exit 1; }
grep -q "\-\-http" "$PROJECT_ROOT/runtime/mcp/server.py" || { echo "FAILED: --http flag missing from server.py"; exit 1; }
grep -q "transport.*sse\|sse.*transport" "$PROJECT_ROOT/runtime/mcp/server.py" || { echo "FAILED: SSE transport missing from server.py"; exit 1; }
grep -q "\-\-http" "$PROJECT_ROOT/runtime/bin/brain-mcp" || { echo "FAILED: --http usage missing from brain-mcp"; exit 1; }
# Startup banner present in code
grep -q "starting.*SSE\|SSE.*starting\|endpoint.*sse\|sse.*endpoint" "$PROJECT_ROOT/runtime/mcp/server.py" || { echo "FAILED: startup banner missing from server.py"; exit 1; }
# _validate_port and _validate_host functions present
grep -q "_validate_port\|_validate_host" "$PROJECT_ROOT/runtime/mcp/server.py" || { echo "FAILED: validation functions missing from server.py"; exit 1; }
# OSError handling present
grep -q "OSError\|cannot bind" "$PROJECT_ROOT/runtime/mcp/server.py" || { echo "FAILED: OSError handling missing from server.py"; exit 1; }
# Unit-test validation functions inline (avoids fastmcp import issue)
_mcp_server_src="$PROJECT_ROOT/runtime/mcp/server.py"
python3 - "$_mcp_server_src" <<'PYEOF'
import sys

# Extract _validate_port and _validate_host from server.py without importing the full module
src_path = sys.argv[1]
src = open(src_path).read()
lines = src.splitlines()
funcs = {}
cur_name = None
cur_lines = []
for line in lines:
    if line.startswith("def _validate_"):
        if cur_name:
            funcs[cur_name] = "\n".join(cur_lines)
        cur_name = line.split("(")[0][4:]  # strip "def "
        cur_lines = [line]
    elif cur_name and (line.startswith("    ") or line == ""):
        cur_lines.append(line)
    elif cur_name:
        funcs[cur_name] = "\n".join(cur_lines)
        cur_name = None
        cur_lines = []
if cur_name:
    funcs[cur_name] = "\n".join(cur_lines)

assert "_validate_port" in funcs, "Missing _validate_port function"
assert "_validate_host" in funcs, "Missing _validate_host function"

ns = {"sys": sys, "print": print}
exec(funcs["_validate_port"], ns)
exec(funcs["_validate_host"], ns)
vp = ns["_validate_port"]
vh = ns["_validate_host"]

# Port 0 → sys.exit(1)
try:
    vp(0); assert False, "port 0 should have exited"
except SystemExit as e:
    assert e.code == 1, f"Expected exit 1, got {e.code}"

# Port 99999 → sys.exit(1)
try:
    vp(99999); assert False, "port 99999 should have exited"
except SystemExit as e:
    assert e.code == 1, f"Expected exit 1, got {e.code}"

# Valid ports pass through
assert vp(8766) == 8766
assert vp(1) == 1
assert vp(65535) == 65535

# Empty host → sys.exit(1)
try:
    vh(""); assert False, "empty host should have exited"
except SystemExit as e:
    assert e.code == 1, f"Expected exit 1, got {e.code}"

# Valid hosts pass through
assert vh("127.0.0.1") == "127.0.0.1"
assert vh("localhost") == "localhost"

print("brain-mcp --http hardening OK")
PYEOF
