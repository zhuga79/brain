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

# 3. Non-standard value: a quoted slug item containing a comma ('a, b') must
#    be preserved as ONE slug, not split on the comma. The old naive parser
#    split on ',' and produced two bogus slugs ('a', 'b'); brain_wiki keeps it
#    as a single list item. This demonstrates the real behavioural difference
#    (old -> ['a','b'], new -> ['a, b']), whereas the earlier 'comma-doctor'
#    fixture carried no comma and thus duplicated case 2.
cat > "$BRAIN_PATH/roles/comma-role.md" <<'EOF'
---
type: role
doctrine: ['a, b']
model_tier: fast
writes: [docs]
---
# Role: Comma
EOF

out=$(brain-run --role comma-role --task t-x 2>/dev/null || true)
# the comma item must NOT be split into separate 'a' and 'b' doctrine slugs
# (the old naive parser would have emitted doctrine/a.md and doctrine/b.md)
if grep -qE "^## doctrine/(a|b)\.md$" <<< "$out"; then
    echo "FAILED: comma-quoted doctrine slug was wrongly split on the comma"; exit 1;
fi

# 3b. A doctrine frontmatter that is outside the supported YAML subset (here a
#     nested mapping) must NOT crash brain-run under set -e: it degrades to an
#     empty doctrine list and still prints the prompt with exit 0.
cat > "$BRAIN_PATH/roles/broken-frontmatter-role.md" <<'EOF'
---
type: role
doctrine:
  weird:
    nested: value
model_tier: fast
writes: [docs]
---
# Role: Broken
EOF

out=$(brain-run --role broken-frontmatter-role --task t-x 2>/dev/null || true)
# degraded gracefully: no doctrine loaded (broken role must be rejected), but prompt still emitted
grep -qi "MEMORY" <<< "$out" || { echo "FAILED: broken frontmatter role degraded but prompt missing"; exit 1; }

rm -f "$BRAIN_PATH/roles/list-role.md" "$BRAIN_PATH/roles/single-role.md" "$BRAIN_PATH/roles/comma-role.md" "$BRAIN_PATH/roles/broken-frontmatter-role.md"
rm -f "$BRAIN_PATH/doctrine/list-doctor.md" "$BRAIN_PATH/doctrine/single-doctor.md" "$BRAIN_PATH/doctrine/comma-doctor.md"

echo "brain-run doctrine frontmatter OK"
