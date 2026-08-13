#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-skill CLI"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

mkdir -p "$BRAIN_PATH/skills/test-cli"
cat << 'YAMLEOF' > "$BRAIN_PATH/skills/test-cli/SKILL.md"
---
name: cli-test-skill
type: knowledge
applies_to: [developer]
supported_clients: [all]
---
Test body.
YAMLEOF

# Test list
out_list=$(python3 "$PROJECT_ROOT/runtime/bin/brain-skill" list)
grep -q "cli-test-skill" <<< "$out_list" || { echo "FAILED: list missing skill"; exit 1; }
grep -q "developer" <<< "$out_list" || { echo "FAILED: list missing applies_to"; exit 1; }
echo "brain-skill list OK"

# Test mount
python3 "$PROJECT_ROOT/runtime/bin/brain-skill" mount cli-test-skill --to-role architect >/dev/null
grep -q "architect" "$BRAIN_PATH/skills/test-cli/SKILL.md" || { echo "FAILED: mount did not add role"; exit 1; }
echo "brain-skill mount OK"

# Test unmount
python3 "$PROJECT_ROOT/runtime/bin/brain-skill" unmount cli-test-skill --from-role developer >/dev/null
grep -q "developer" "$BRAIN_PATH/skills/test-cli/SKILL.md" && { echo "FAILED: unmount did not remove role"; exit 1; }
echo "brain-skill unmount OK"

# Test ingest-book
touch /tmp/dummy-book.txt
python3 "$PROJECT_ROOT/runtime/bin/brain-skill" ingest-book /tmp/dummy-book.txt --to-role developer >/dev/null
[ -f "$BRAIN_PATH/wiki/concept-dummy-book-glossary.md" ] || { echo "FAILED: ingest-book did not create glossary"; exit 1; }
[ -f "$BRAIN_PATH/skills/dummy-book/SKILL.md" ] || { echo "FAILED: ingest-book did not create skill"; exit 1; }
grep -q "developer" "$BRAIN_PATH/skills/dummy-book/SKILL.md" || { echo "FAILED: ingest-book did not assign role"; exit 1; }
echo "brain-skill ingest-book OK"
rm -f /tmp/dummy-book.txt

# Regression: installed brain-skill must work without PYTHONPATH or source-tree paths.
BRAIN_PATH="$BRAIN_PATH" bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null
hash -r
set +e
out_installed=$(PATH="$HOME/.local/bin:/usr/bin:/bin" BRAIN_PATH="$BRAIN_PATH" brain-skill list 2>&1)
installed_rc=$?
set -e
[ "$installed_rc" -eq 0 ] || {
  echo "FAILED: installed brain-skill exited $installed_rc"
  echo "$out_installed"
  exit 1
}
grep -q "cli-test-skill" <<< "$out_installed" || {
  echo "FAILED: installed brain-skill cannot import runtime skill libs"
  echo "$out_installed"
  exit 1
}
echo "installed brain-skill OK"
