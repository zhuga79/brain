#!/usr/bin/env bash
# case: split-layout — data tree without system dirs; validate green; runtime/ back is red
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Building isolated split layout"

data="$(mktemp -d)"
system="$(mktemp -d)"
ALL_TMPDIRS+=("$data" "$system")

export BRAIN_PATH="$data"
export BRAIN="$data"
export BRAIN_SYSTEM_PATH="$system"

for d in wiki tasks raw council handoff learning prd .locks; do
  mkdir -p "$data/$d"
done
touch "$data/tasks/active.md" "$data/tasks/done.md"
printf '# Log\n' > "$data/wiki/log.md"
cat > "$data/wiki/index.md" <<'EOF'
# Index
[[work-notes]]
EOF
cat > "$data/wiki/work-notes.md" <<'EOF'
---
title: Work Notes
type: concept
created: 2026-08-14
updated: 2026-08-14
curation: agent
protected: false
source_policy: advisory
tags: []
sources: []
related: []
---

# Work Notes

See [[decision-foo]].
EOF

mkdir -p "$system/roles" "$system/docs/decisions" "$system/runtime/bin" "$system/config"
cat > "$system/roles/developer.md" <<'EOF'
---
type: role
doctrine: []
model_tier: fast
writes: [code]
---
# Role: developer
EOF
cat > "$system/config/routing.json" <<'EOF'
{
  "version": 2,
  "profiles": {
    "fast": [{"rank": 1, "provider": "none", "model": "x", "command": "true"}]
  },
  "providers": {"none": {}},
  "roles": {"developer": {"profile": "fast"}}
}
EOF
cat > "$system/docs/decisions/decision-foo.md" <<'EOF'
---
title: Decision Foo
type: decision
created: 2026-08-14
updated: 2026-08-14
curation: agent
protected: false
source_policy: advisory
tags: []
sources: []
related: []
---

# Decision Foo
EOF

echo ">>> Data tree must not carry exclusive system dirs"
for d in runtime tests spec docs roles teams doctrine skills; do
  [ ! -e "$data/$d" ] || fail_case "data tree still has $d/"
done
for d in wiki tasks raw council handoff learning prd .locks; do
  [ -d "$data/$d" ] || fail_case "data tree missing $d/"
done

echo ">>> Roles resolve from SYSTEM_PATH"
python3 - <<'PY'
import os
from pathlib import Path
from brain_core.paths import iter_system_files, resolve_system_asset

data = Path(os.environ["BRAIN_PATH"])
system = Path(os.environ["BRAIN_SYSTEM_PATH"])
role = resolve_system_asset("roles/developer.md")
assert role == system / "roles" / "developer.md", role
assert role.is_file(), role
stems = {p.stem for p in iter_system_files("roles", "*.md")}
assert "developer" in stems, stems
assert not (data / "roles").exists()
print("OK: roles resolve from system")
PY

echo ">>> brain-validate green on split layout"
validate_out="$(brain-validate 2>&1)" || {
  echo "FAILED: brain-validate should pass on split layout"
  echo "$validate_out"
  exit 1
}
echo "$validate_out" | grep -q "OK: Brain validation passed" || {
  echo "FAILED: expected OK from brain-validate"
  echo "$validate_out"
  exit 1
}
echo "$validate_out" | grep -q "системный путь восстановлен" && {
  echo "FAILED: empty exclusive dirs treated as restored"
  echo "$validate_out"
  exit 1
}

echo ">>> brain-validate red if runtime/ is put back"
mkdir -p "$data/runtime"
set +e
restored_out="$(brain-validate 2>&1)"
restored_rc=$?
set -e
[ "$restored_rc" -ne 0 ] || {
  echo "FAILED: runtime/ in the data tree should fail validate"
  echo "$restored_out"
  exit 1
}
echo "$restored_out" | grep -q "системный путь восстановлен в приватном дереве" || {
  echo "FAILED: missing restore-check message for runtime/"
  echo "$restored_out"
  exit 1
}
rm -rf "$data/runtime"

echo ">>> split-layout checks passed"
