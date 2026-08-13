#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying UI/UX skill templates"

grep -q "skills/uiux" "$BRAIN_PATH/roles/designer.md" || { echo "FAILED: designer role missing UI/UX skill routing"; exit 1; }
grep -q "\[product, designer, developer, reviewer\]" "$BRAIN_PATH/roles/designer.md" || { echo "FAILED: designer role missing UI/UX council routing"; exit 1; }
grep -q "\[product, designer, developer, reviewer\]" "$BRAIN_PATH/roles/product.md" || { echo "FAILED: product role missing UI/UX council routing"; exit 1; }
grep -q "ux-task-framing" "$BRAIN_PATH/roles/product.md" || { echo "FAILED: product role missing ux-task-framing awareness"; exit 1; }
grep -q "\[product, designer, developer, reviewer\]" "$BRAIN_PATH/roles/developer.md" || { echo "FAILED: developer role missing UI/UX council routing"; exit 1; }
grep -q "frontend-handoff-spec" "$BRAIN_PATH/roles/developer.md" || { echo "FAILED: developer role missing handoff awareness"; exit 1; }
grep -q "\[product, designer, developer, reviewer\]" "$BRAIN_PATH/roles/reviewer.md" || { echo "FAILED: reviewer role missing UI/UX council routing"; exit 1; }
grep -q "design-system-guard" "$BRAIN_PATH/roles/reviewer.md" || { echo "FAILED: reviewer role missing design-system awareness"; exit 1; }
grep -q "microcopy-coordination" "$BRAIN_PATH/roles/copywriter.md" || { echo "FAILED: copywriter role missing microcopy awareness"; exit 1; }
grep -q "skill pack hygiene" "$BRAIN_PATH/roles/linter.md" || { echo "FAILED: linter role missing skill-pack ownership"; exit 1; }

core_slugs=(
  ux-task-framing
  workflow-design
  information-architecture
  design-system-guard
  accessibility-review
  ui-critique
)

for slug in "${core_slugs[@]}"; do
  path="$BRAIN_PATH/skills/uiux/core/$slug.md"
  [ -f "$path" ] || { echo "FAILED: missing core UI/UX skill $slug"; exit 1; }
  grep -q "^name: $slug$" "$path" || { echo "FAILED: skill $slug name mismatch"; exit 1; }
  grep -q "^group: core$" "$path" || { echo "FAILED: skill $slug group mismatch"; exit 1; }
  grep -q "^status: active$" "$path" || { echo "FAILED: skill $slug must be active"; exit 1; }
  grep -q "^trigger: " "$path" || { echo "FAILED: skill $slug missing trigger"; exit 1; }
  grep -q "^output_format: " "$path" || { echo "FAILED: skill $slug missing output_format"; exit 1; }
  grep -q "^## Trigger$" "$path" || { echo "FAILED: skill $slug missing Trigger section"; exit 1; }
  grep -q "^## Inputs$" "$path" || { echo "FAILED: skill $slug missing Inputs section"; exit 1; }
  grep -q "^## Checklist$" "$path" || { echo "FAILED: skill $slug missing Checklist section"; exit 1; }
  grep -q "^## Output Format$" "$path" || { echo "FAILED: skill $slug missing Output Format section"; exit 1; }
  grep -q "^## Forbidden$" "$path" || { echo "FAILED: skill $slug missing Forbidden section"; exit 1; }
  grep -q "^## See Also$" "$path" || { echo "FAILED: skill $slug missing See Also section"; exit 1; }
  grep -q "empty:" "$path" || { echo "FAILED: skill $slug missing state matrix empty"; exit 1; }
  grep -q "loading:" "$path" || { echo "FAILED: skill $slug missing state matrix loading"; exit 1; }
  grep -q "error:" "$path" || { echo "FAILED: skill $slug missing state matrix error"; exit 1; }
  grep -q "success:" "$path" || { echo "FAILED: skill $slug missing state matrix success"; exit 1; }
  grep -q "disabled:" "$path" || { echo "FAILED: skill $slug missing state matrix disabled"; exit 1; }
done

brain_slugs=(
  data-dense-dashboard-design
  ai-product-ux
  orchestration-ui-patterns
)

for slug in "${brain_slugs[@]}"; do
  path="$BRAIN_PATH/skills/uiux/brain/$slug.md"
  [ -f "$path" ] || { echo "FAILED: missing Brain UI/UX skill $slug"; exit 1; }
  grep -q "^name: $slug$" "$path" || { echo "FAILED: skill $slug name mismatch"; exit 1; }
  grep -q "^group: brain$" "$path" || { echo "FAILED: skill $slug group mismatch"; exit 1; }
  grep -q "^status: active$" "$path" || { echo "FAILED: skill $slug must be active"; exit 1; }
  grep -q "^trigger: " "$path" || { echo "FAILED: skill $slug missing trigger"; exit 1; }
  grep -q "^## Forbidden$" "$path" || { echo "FAILED: skill $slug missing Forbidden section"; exit 1; }
  grep -q "empty:" "$path" || { echo "FAILED: skill $slug missing state matrix empty"; exit 1; }
  grep -q "loading:" "$path" || { echo "FAILED: skill $slug missing state matrix loading"; exit 1; }
  grep -q "error:" "$path" || { echo "FAILED: skill $slug missing state matrix error"; exit 1; }
  grep -q "success:" "$path" || { echo "FAILED: skill $slug missing state matrix success"; exit 1; }
  grep -q "disabled:" "$path" || { echo "FAILED: skill $slug missing state matrix disabled"; exit 1; }
done

handoff_active_slugs=(
  frontend-handoff-spec
  responsive-behavior-spec
  microcopy-coordination
)

for slug in "${handoff_active_slugs[@]}"; do
  path="$BRAIN_PATH/skills/uiux/handoff/$slug.md"
  [ -f "$path" ] || { echo "FAILED: missing handoff UI/UX skill $slug"; exit 1; }
  grep -q "^name: $slug$" "$path" || { echo "FAILED: skill $slug name mismatch"; exit 1; }
  grep -q "^group: handoff$" "$path" || { echo "FAILED: skill $slug group mismatch"; exit 1; }
  grep -q "^status: active$" "$path" || { echo "FAILED: skill $slug must be active"; exit 1; }
  grep -q "^trigger: " "$path" || { echo "FAILED: skill $slug missing trigger"; exit 1; }
  grep -q "^## Output Format$" "$path" || { echo "FAILED: skill $slug missing Output Format section"; exit 1; }
done

handoff_draft_slugs=(
  visual-regression-checklist
  usability-test-script
)

for slug in "${handoff_draft_slugs[@]}"; do
  path="$BRAIN_PATH/skills/uiux/handoff/$slug.md"
  [ -f "$path" ] || { echo "FAILED: missing draft handoff UI/UX skill $slug"; exit 1; }
  grep -q "^name: $slug$" "$path" || { echo "FAILED: draft skill $slug name mismatch"; exit 1; }
  grep -q "^group: handoff$" "$path" || { echo "FAILED: draft skill $slug group mismatch"; exit 1; }
  grep -q "^status: draft$" "$path" || { echo "FAILED: draft skill $slug must be draft"; exit 1; }
done

all_skill_paths=(
  "$BRAIN_PATH"/skills/uiux/core/*.md
  "$BRAIN_PATH"/skills/uiux/brain/*.md
  "$BRAIN_PATH"/skills/uiux/handoff/*.md
)

for path in "${all_skill_paths[@]}"; do
  [ -f "$path" ] || { echo "FAILED: missing UI/UX skill path $path"; exit 1; }
  slug="$(basename "$path" .md)"
  group="$(basename "$(dirname "$path")")"
  bytes="$(wc -c < "$path")"
  [ "$bytes" -le 8192 ] || { echo "FAILED: skill $slug exceeds 8KB"; exit 1; }
  grep -q "^name: $slug$" "$path" || { echo "FAILED: skill $slug name mismatch"; exit 1; }
  grep -q "^version: " "$path" || { echo "FAILED: skill $slug missing version"; exit 1; }
  grep -q "^last_updated: " "$path" || { echo "FAILED: skill $slug missing last_updated"; exit 1; }
  grep -Eq "^status: (active|draft)$" "$path" || { echo "FAILED: skill $slug invalid status"; exit 1; }
  grep -q "^owner_role: " "$path" || { echo "FAILED: skill $slug missing owner_role"; exit 1; }
  grep -q "^group: $group$" "$path" || { echo "FAILED: skill $slug group mismatch"; exit 1; }
  grep -q "^applies_to: .*designer" "$path" || { echo "FAILED: skill $slug must apply to designer"; exit 1; }
  grep -q "^invoked_by: " "$path" || { echo "FAILED: skill $slug missing invoked_by"; exit 1; }
  grep -q "^consumed_by: " "$path" || { echo "FAILED: skill $slug missing consumed_by"; exit 1; }
  grep -q "^requires: " "$path" || { echo "FAILED: skill $slug missing requires"; exit 1; }
  grep -q "^forbidden_zones: " "$path" || { echo "FAILED: skill $slug missing forbidden_zones"; exit 1; }
  grep -q "^max_lines: " "$path" || { echo "FAILED: skill $slug missing max_lines"; exit 1; }
  max_lines="$(sed -n 's/^max_lines: //p' "$path")"
  [ "$max_lines" -le 200 ] || { echo "FAILED: skill $slug max_lines exceeds 200"; exit 1; }
  grep -q "^## Trigger$" "$path" || { echo "FAILED: skill $slug missing Trigger section"; exit 1; }
  grep -q "^## Inputs$" "$path" || { echo "FAILED: skill $slug missing Inputs section"; exit 1; }
  grep -q "^## Checklist$" "$path" || { echo "FAILED: skill $slug missing Checklist section"; exit 1; }
  grep -q "^## Output Format$" "$path" || { echo "FAILED: skill $slug missing Output Format section"; exit 1; }
  grep -q "^## Forbidden$" "$path" || { echo "FAILED: skill $slug missing Forbidden section"; exit 1; }
  grep -q "^## See Also$" "$path" || { echo "FAILED: skill $slug missing See Also section"; exit 1; }
done

# Кейс отвечает за скилл-пак UI/UX, а не за здоровье общей фабрики: другие
# кейсы правят её конфигурацию маршрутизации, и падение brain-validate по их
# причинам к этой проверке отношения не имеет.
set +e
brain-validate >/tmp/brain_uiux_validate_ok.log 2>&1
set -e
if grep -qE "(skills/|UI/UX|uiux)" /tmp/brain_uiux_validate_ok.log; then
  echo "FAILED: brain-validate rejected valid UI/UX skill pack"
  grep -E "(skills/|UI/UX|uiux)" /tmp/brain_uiux_validate_ok.log
  exit 1
fi

missing_skill="$BRAIN_PATH/skills/uiux/core/ux-task-framing.md"
missing_backup="/tmp/brain_uiux_missing_skill.md"
mv "$missing_skill" "$missing_backup"
set +e
brain-validate >/tmp/brain_uiux_validate_missing.out 2>&1
validate_missing_rc=$?
set -e
mv "$missing_backup" "$missing_skill"
[ "$validate_missing_rc" -ne 0 ] || {
  echo "FAILED: brain-validate accepted missing required UI/UX skill"
  cat /tmp/brain_uiux_validate_missing.out
  exit 1
}
grep -q "missing required UI/UX skill" /tmp/brain_uiux_validate_missing.out || {
  echo "FAILED: brain-validate missing skill error was unclear"
  cat /tmp/brain_uiux_validate_missing.out
  exit 1
}

brain-lint --quiet >/tmp/brain_uiux_lint_ok.log || {
  echo "FAILED: brain-lint rejected valid UI/UX skill references"
  cat /tmp/brain_uiux_lint_ok.log
  exit 1
}

mkdir -p "$BRAIN_PATH/handoff"
cat > "$BRAIN_PATH/handoff/test-broken-skill-ref.md" <<'EOF'
# Broken UI/UX skill reference

This file points at `skills/uiux/core/not-a-real-skill`.
EOF
set +e
brain-lint --quiet >/tmp/brain_uiux_lint_broken.out 2>&1
lint_broken_rc=$?
set -e
rm -f "$BRAIN_PATH/handoff/test-broken-skill-ref.md"
[ "$lint_broken_rc" -ne 0 ] || {
  echo "FAILED: brain-lint accepted broken UI/UX skill reference"
  cat /tmp/brain_uiux_lint_broken.out
  exit 1
}
grep -q "broken skill reference: skills/uiux/core/not-a-real-skill" /tmp/brain_uiux_lint_broken.out || {
  echo "FAILED: brain-lint broken skill error was unclear"
  cat /tmp/brain_uiux_lint_broken.out
  exit 1
}

echo "UI/UX skills OK"
