#!/usr/bin/env bash
# case: split-root-update-guard — setup/update keep data MEMORY and do not restore system dirs
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Building isolated split-root checkout copy"

brain_factory
data="$BRAIN_PATH"
system="$BRAIN_FACTORY_TMP/system"
mkdir -p "$system"

cp "$PROJECT_ROOT/setup-brain-v2.sh" "$system/"
cp "$PROJECT_ROOT/install-brain-mcp.sh" "$system/"
cp "$PROJECT_ROOT/pyproject.toml" "$system/"
cp -R "$PROJECT_ROOT/runtime" "$system/"
cp -R "$PROJECT_ROOT/roles" "$system/"
cp -R "$PROJECT_ROOT/teams" "$system/"
cp -R "$PROJECT_ROOT/doctrine" "$system/"
cp -R "$PROJECT_ROOT/wiki" "$system/"
cp -R "$PROJECT_ROOT/skills" "$system/"
cp -R "$PROJECT_ROOT/config" "$system/"
mkdir -p "$system/tests"
cat > "$system/tests/run.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$system/tests/run.sh"
git -C "$system" init >/dev/null 2>&1
git -C "$system" config user.email "case@example.com"
git -C "$system" config user.name "case"
git -C "$system" add -A >/dev/null 2>&1
git -C "$system" commit -m "system checkout" >/dev/null 2>&1
system_remote="$BRAIN_FACTORY_TMP/system-remote.git"
git init --bare "$system_remote" >/dev/null 2>&1
git -C "$system" remote add origin "$system_remote"
git -C "$system" push -u origin HEAD >/dev/null 2>&1

mkdir -p "$data/wiki" "$data/tasks" "$data/raw" "$data/council" "$data/.locks" "$data/teams"
cat > "$data/MEMORY.md" <<'EOF'
# private marker
owner: data-root
EOF
printf '# Active\n' > "$data/tasks/active.md"
printf '# Done\n' > "$data/tasks/done.md"
printf '# Index\n' > "$data/wiki/index.md"
printf '# Log\n' > "$data/wiki/log.md"
cat > "$data/teams/insurance-fraud.md" <<'EOF'
---
title: Insurance Fraud
type: team
roles: [developer]
---
EOF

echo ">>> direct setup auto-detects split-root without BRAIN_SYSTEM_PATH"
unset BRAIN_SYSTEM_PATH
bash "$system/setup-brain-v2.sh" >/dev/null
grep -q '^# private marker$' "$data/MEMORY.md" || {
  echo "FAILED: direct setup overwrote data MEMORY.md"
  cat "$data/MEMORY.md"
  exit 1
}
for d in roles doctrine skills config; do
  [ ! -e "$data/$d" ] || {
    echo "FAILED: direct setup restored $d/ into data root"
    exit 1
  }
done
[ -f "$data/teams/insurance-fraud.md" ] || {
  echo "FAILED: direct setup removed allowed data teams asset"
  exit 1
}

export BRAIN_SYSTEM_PATH="$system"

echo ">>> setup still preserves private MEMORY with explicit BRAIN_SYSTEM_PATH"
bash "$system/setup-brain-v2.sh" >/dev/null
grep -q '^# private marker$' "$data/MEMORY.md" || {
  echo "FAILED: explicit split-root setup overwrote data MEMORY.md"
  cat "$data/MEMORY.md"
  exit 1
}

echo ">>> brain-validate rejects restored system shadows but allows data teams asset"
brain-validate >/dev/null 2>&1 || {
  echo "FAILED: brain-validate should stay green without system shadows"
  brain-validate 2>&1 || true
  exit 1
}
mkdir -p "$data/config"
set +e
shadow_out="$(brain-validate 2>&1)"
shadow_rc=$?
set -e
[ "$shadow_rc" -ne 0 ] || {
  echo "FAILED: brain-validate should fail on config/ shadow"
  exit 1
}
echo "$shadow_out" | grep -q "config/" || {
  echo "FAILED: validate output missing config/ shadow path"
  echo "$shadow_out"
  exit 1
}
rm -rf "$data/config"

echo ">>> brain-validate rejects a stale installer shadow in the data root"
cp "$PROJECT_ROOT/setup-brain-v2.sh" "$data/setup-brain-v2.sh"
cp "$PROJECT_ROOT/pyproject.toml" "$data/pyproject.toml"
set +e
installer_out="$(brain-validate 2>&1)"
installer_rc=$?
set -e
[ "$installer_rc" -ne 0 ] || {
  echo "FAILED: brain-validate should fail on an installer shadow in the data root"
  echo "$installer_out"
  exit 1
}
echo "$installer_out" | grep -q "ERROR: setup-brain-v2.sh: installer-тень в дереве данных" || {
  echo "FAILED: missing installer-shadow diagnostic for setup-brain-v2.sh"
  echo "$installer_out"
  exit 1
}
echo "$installer_out" | grep -q "перезаписывает операторский MEMORY.md" || {
  echo "FAILED: installer-shadow diagnostic does not say what breaks"
  echo "$installer_out"
  exit 1
}
echo "$installer_out" | grep -qF "$system/setup-brain-v2.sh" || {
  echo "FAILED: installer-shadow diagnostic does not name the canonical file"
  echo "$installer_out"
  exit 1
}
echo "$installer_out" | grep -q "ERROR: pyproject.toml: installer-тень в дереве данных" || {
  echo "FAILED: missing installer-shadow diagnostic for pyproject.toml"
  echo "$installer_out"
  exit 1
}
rm -f "$data/setup-brain-v2.sh" "$data/pyproject.toml"
brain-validate >/dev/null 2>&1 || {
  echo "FAILED: brain-validate should be green again once the shadow is gone"
  brain-validate 2>&1 || true
  exit 1
}

echo ">>> pre-commit write-path guard rejects re-adding an installer shadow"
git -C "$data" init >/dev/null 2>&1 || true
git -C "$data" config user.email "case@example.com"
git -C "$data" config user.name "case"
cp "$PROJECT_ROOT/setup-brain-v2.sh" "$data/setup-brain-v2.sh"
git -C "$data" add -f setup-brain-v2.sh >/dev/null
set +e
guard_out="$(cd "$data" && "$PROJECT_ROOT/runtime/hooks/pre-commit-write-path" 2>&1)"
guard_rc=$?
set -e
[ "$guard_rc" -ne 0 ] || {
  echo "FAILED: write-path guard accepted a staged installer shadow"
  echo "$guard_out"
  exit 1
}
echo "$guard_out" | grep -q "setup-brain-v2.sh — запуск из корня данных" || {
  echo "FAILED: write-path guard did not explain the installer shadow"
  echo "$guard_out"
  exit 1
}
git -C "$data" reset -q >/dev/null 2>&1 || true
rm -f "$data/setup-brain-v2.sh"

echo ">>> legacy single-root setup remains working"
single="$BRAIN_FACTORY_TMP/single-root"
mkdir -p "$single"
cp "$PROJECT_ROOT/setup-brain-v2.sh" "$single/"
cp "$PROJECT_ROOT/install-brain-mcp.sh" "$single/"
cp -R "$PROJECT_ROOT/runtime" "$single/"
unset BRAIN_SYSTEM_PATH
BRAIN_PATH="$single" bash "$single/setup-brain-v2.sh" >/dev/null
for d in roles teams doctrine skills; do
  [ -d "$single/$d" ] || {
    echo "FAILED: single-root setup did not create $d/"
    exit 1
  }
done
[ -f "$single/MEMORY.md" ] || {
  echo "FAILED: single-root setup did not create MEMORY.md"
  exit 1
}

echo ">>> brain-ops update keeps data MEMORY and skips system shadows"
export BRAIN_SYSTEM_PATH="$system"
mkdir -p "$BRAIN_FACTORY_TMP/bin"
cat > "$BRAIN_FACTORY_TMP/bin/git" <<'EOF'
#!/usr/bin/env bash
# Only short-circuit `pull`; every other subcommand (including the upstream
# checks brain-ops now runs first) must still see the original arguments —
# in particular `-C <dir>` — or it silently falls back to the caller's cwd.
sub="$1"
if [ "$sub" = "-C" ]; then
  sub="$3"
fi
if [ "$sub" = "pull" ]; then
  exit 0
fi
exec /usr/bin/git "$@"
EOF
chmod +x "$BRAIN_FACTORY_TMP/bin/git"
export PATH="$BRAIN_FACTORY_TMP/bin:$PATH"

echo ">>> setup/update refresh an existing MCP install but keep absent MCP opt-in"
cp "$PROJECT_ROOT/install-brain-mcp.sh" "$system/"
mkdir -p "$HOME/.local/bin"
python3 -m venv "$HOME/.local/share/brain-mcp/.venv"
site_dir="$("$HOME/.local/share/brain-mcp/.venv/bin/python" - <<'PY'
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
cat > "$HOME/.local/share/brain-mcp/.venv/bin/pip" <<'EOF'
#!/usr/bin/env bash
echo "pip should not run during existing MCP refresh" >&2
exit 97
EOF
chmod +x "$HOME/.local/share/brain-mcp/.venv/bin/pip"
mkdir -p "$HOME/.local/share/brain-mcp/runtime/mcp"
printf 'legacy\n' > "$HOME/.local/share/brain-mcp/runtime/mcp/server.py"
cat > "$HOME/.local/bin/brain-mcp" <<'EOF'
#!/usr/bin/env bash
echo stale launcher
EOF
chmod +x "$HOME/.local/bin/brain-mcp"

"$PROJECT_ROOT/runtime/bin/brain-ops" update >/dev/null
grep -q '^# private marker$' "$data/MEMORY.md" || {
  echo "FAILED: update overwrote data MEMORY.md"
  cat "$data/MEMORY.md"
  exit 1
}
for d in roles doctrine skills config; do
  [ ! -e "$data/$d" ] || {
    echo "FAILED: update restored $d/ into data root"
    exit 1
  }
done
[ -f "$data/teams/insurance-fraud.md" ] || {
  echo "FAILED: update removed allowed data teams asset"
  exit 1
}
python3 "$PROJECT_ROOT/runtime/mcp/packaging.py" verify --system-root "$system" --install-root "$HOME/.local/share/brain-mcp" >/tmp/mcp-refresh-verify.out || {
  cat /tmp/mcp-refresh-verify.out
  echo "FAILED: update did not refresh the existing MCP install"
  exit 1
}

rm -rf "$HOME/.local/share/brain-mcp" "$HOME/.local/bin/brain-mcp"
"$PROJECT_ROOT/runtime/bin/brain-ops" update >/dev/null
[ ! -e "$HOME/.local/share/brain-mcp" ] || {
  echo "FAILED: update installed MCP even though it was absent"
  exit 1
}
[ ! -e "$HOME/.local/bin/brain-mcp" ] || {
  echo "FAILED: update recreated the MCP launcher even though MCP was absent"
  exit 1
}

echo ">>> split-root update guard checks passed"
