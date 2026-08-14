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

echo ">>> legacy single-root setup remains working"
single="$BRAIN_FACTORY_TMP/single-root"
mkdir -p "$single"
cp "$PROJECT_ROOT/setup-brain-v2.sh" "$single/"
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
if [ "$1" = "-C" ]; then
  shift 2
fi
if [ "${1:-}" = "pull" ]; then
  exit 0
fi
exec /usr/bin/git "$@"
EOF
chmod +x "$BRAIN_FACTORY_TMP/bin/git"
export PATH="$BRAIN_FACTORY_TMP/bin:$PATH"

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

echo ">>> split-root update guard checks passed"
