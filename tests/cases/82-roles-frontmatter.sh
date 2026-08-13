#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying role frontmatter validation"

# 1. Every repo role file carries machine-readable frontmatter (type: role)
#    and references only existing doctrines. We check the repo source of truth:
#    the factory brain roles are mutated by other cases (e.g. 11-dashboard-post
#    overwrites lawyer.md), so the factory is not a stable target.
python3 - <<'PYEOF'
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["PROJECT_ROOT"] + "/runtime/lib")
from brain_wiki import parse_frontmatter

repo = Path(os.environ["PROJECT_ROOT"])
roles_dir = repo / "roles"
doctrine_dir = repo / "doctrine"
assert roles_dir.is_dir(), f"roles dir missing: {roles_dir}"
broken = []
for path in sorted(roles_dir.glob("*.md")):
    fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    if not fm:
        broken.append(f"{path.name}: no frontmatter")
        continue
    if fm.get("type") != "role":
        broken.append(f"{path.name}: type={fm.get('type')!r}")
    for slug in (fm.get("doctrine") or []):
        if not (doctrine_dir / f"{slug}.md").is_file():
            broken.append(f"{path.name}: doctrine={slug} missing")
assert not broken, "repo roles invalid:\n" + "\n".join(broken)
print(f"repo roles frontmatter OK ({len(list(roles_dir.glob('*.md')))} roles)")
PYEOF

# 1b. Heredoc role writers in add-*.sh also carry frontmatter
python3 - <<'PYEOF'
import os
import re
from pathlib import Path

repo = Path(os.environ["PROJECT_ROOT"])
missing = []
for fname in ("add-teams-brain.sh", "add-pm-finance-brain.sh", "add-design-negotiator-brain.sh"):
    text = (repo / fname).read_text(encoding="utf-8")
    for m in re.finditer(r'cat > "\$BRAIN/roles/([a-z0-9-]+)\.md" <<\'EOF\'\n(.*?)\nEOF', text, re.S):
        slug, body = m.group(1), m.group(2)
        if not body.startswith("---\ntype: role"):
            missing.append(f"{fname}:{slug}")
assert not missing, "heredoc role writers without frontmatter:\n" + "\n".join(missing)
print("heredoc role writers frontmatter OK")
PYEOF

# 2. Role without frontmatter → error
cat > "$BRAIN_PATH/roles/broken-role.md" <<'EOF'
# Role: Broken

Ты — роль без frontmatter.
EOF
set +e
brain-validate > /tmp/brain_validate_roles_nofm.log 2>&1
no_fm_exit=$?
set -e
[ "$no_fm_exit" -ne 0 ] || { echo "FAILED: brain-validate should fail on role without frontmatter"; exit 1; }
grep -q "роль без frontmatter" /tmp/brain_validate_roles_nofm.log || {
    echo "FAILED: role-without-frontmatter error not reported"
    cat /tmp/brain_validate_roles_nofm.log
    exit 1
}
rm -f "$BRAIN_PATH/roles/broken-role.md"

# 3. Role referencing non-existent doctrine → error
cat > "$BRAIN_PATH/roles/bad-doctrine-role.md" <<'EOF'
---
type: role
doctrine: [does-not-exist-doctrine]
model_tier: powerful
writes: [docs]
---
# Role: Bad Doctrine
EOF
set +e
brain-validate > /tmp/brain_validate_roles_baddoct.log 2>&1
bad_doct_exit=$?
set -e
[ "$bad_doct_exit" -ne 0 ] || { echo "FAILED: brain-validate should fail on role referencing missing doctrine"; exit 1; }
grep -q "нет файла doctrine/does-not-exist-doctrine.md" /tmp/brain_validate_roles_baddoct.log || {
    echo "FAILED: missing doctrine ref not reported"
    cat /tmp/brain_validate_roles_baddoct.log
    exit 1
}
rm -f "$BRAIN_PATH/roles/bad-doctrine-role.md"

# 4. Role with wrong type → error
cat > "$BRAIN_PATH/roles/wrong-type-role.md" <<'EOF'
---
type: concept
doctrine: []
model_tier: powerful
writes: [docs]
---
# Role: Wrong Type
EOF
set +e
brain-validate > /tmp/brain_validate_roles_badtype.log 2>&1
bad_type_exit=$?
set -e
[ "$bad_type_exit" -ne 0 ] || { echo "FAILED: brain-validate should fail on role with wrong type"; exit 1; }
grep -q "ожидается 'role'" /tmp/brain_validate_roles_badtype.log || {
    echo "FAILED: wrong-type error not reported"
    cat /tmp/brain_validate_roles_badtype.log
    exit 1
}
rm -f "$BRAIN_PATH/roles/wrong-type-role.md"

echo "role frontmatter validation OK"
