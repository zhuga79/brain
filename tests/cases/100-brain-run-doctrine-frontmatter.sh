#!/usr/bin/env bash
# brain-run loads doctrine via the canonical brain_wiki.frontmatter parser
# (t-2026-08-30-follow-up-dup-parsers-frontmat): the inline naive
# split(":", 1) + local as_list in the doctrine block was replaced. Behavior
# for existing roles is unchanged; a quoted item containing a comma is now
# preserved as one slug instead of being split on the comma.
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-run doctrine loading via brain_wiki.frontmatter"

mkdir -p "$BRAIN_PATH/roles" "$BRAIN_PATH/doctrine"

cat > "$BRAIN_PATH/doctrine/list-doctor.md" <<'EOF'
# List demo doctrine
EOF
cat > "$BRAIN_PATH/doctrine/single-doctor.md" <<'EOF'
# Single demo doctrine
EOF
cat > "$BRAIN_PATH/doctrine/comma-doctor.md" <<'EOF'
# Comma demo doctrine
EOF

# 1. doctrine: [a, b] — flow list loads both files.
cat > "$BRAIN_PATH/roles/list-role.md" <<'EOF'
---
type: role
doctrine: [list-doctor, single-doctor]
model_tier: fast
writes: [docs]
---
# Role: List
EOF

out=$(brain-run --role list-role --task t-x 2>/dev/null || true)
grep -q "## doctrine/list-doctor.md" <<< "$out" || { echo "FAILED: list doctrine slug 1 missing"; exit 1; }
grep -q "## doctrine/single-doctor.md" <<< "$out" || { echo "FAILED: list doctrine slug 2 missing"; exit 1; }

# 2. doctrine single non-bracketed string loads.
cat > "$BRAIN_PATH/roles/single-role.md" <<'EOF'
---
type: role
doctrine: single-doctor
model_tier: fast
writes: [docs]
---
# Role: Single
EOF

out=$(brain-run --role single-role --task t-x 2>/dev/null || true)
grep -q "## doctrine/single-doctor.md" <<< "$out" || { echo "FAILED: single doctrine string missing"; exit 1; }

# 3. Non-standard value: a quoted item containing a comma must stay one slug.
#    The old naive parser split on the comma and dropped inside-quotes commas;
#    brain_wiki preserves it as a single list item.
cat > "$BRAIN_PATH/roles/comma-role.md" <<'EOF'
---
type: role
doctrine: ['comma-doctor']
model_tier: fast
writes: [docs]
---
# Role: Comma
EOF

out=$(brain-run --role comma-role --task t-x 2>/dev/null || true)
grep -q "## doctrine/comma-doctor.md" <<< "$out" || { echo "FAILED: comma-quoted doctrine slug missing"; exit 1; }
# и не превращается в обрезанный/неверный slug
grep -q "comma-doctor" <<< "$out"

rm -f "$BRAIN_PATH/roles/list-role.md" "$BRAIN_PATH/roles/single-role.md" "$BRAIN_PATH/roles/comma-role.md"
rm -f "$BRAIN_PATH/doctrine/list-doctor.md" "$BRAIN_PATH/doctrine/single-doctor.md" "$BRAIN_PATH/doctrine/comma-doctor.md"

echo "brain-run doctrine frontmatter OK"
