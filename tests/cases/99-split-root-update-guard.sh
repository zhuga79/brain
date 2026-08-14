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

export BRAIN_SYSTEM_PATH="$system"

echo ">>> setup preserves private MEMORY and skips system shadows"
bash "$system/setup-brain-v2.sh" >/dev/null
grep -q '^# private marker$' "$data/MEMORY.md" || {
  echo "FAILED: setup overwrote data MEMORY.md"
  cat "$data/MEMORY.md"
  exit 1
}
for d in roles doctrine skills config; do
  [ ! -e "$data/$d" ] || {
    echo "FAILED: setup restored $d/ into data root"
    exit 1
  }
done
[ -f "$data/teams/insurance-fraud.md" ] || {
  echo "FAILED: setup removed allowed data teams asset"
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

echo ">>> brain-ops update keeps data MEMORY and skips system shadows"
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
