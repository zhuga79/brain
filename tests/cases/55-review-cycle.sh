#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying recurring review cycle automation"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki"
cat > "$BRAIN_PATH/tasks/active.md" <<'EOF'
# Active Tasks

- [ ] [P1] t-2026-05-29-dashboard-search — Dashboard search needs stabilization
      role: developer   mode: solo
      acceptance: TODO

- [ ] [P1] t-2026-05-29-workspace-import — Workspace import flow
      role: product   mode: solo
      acceptance: TODO
EOF
cat > "$BRAIN_PATH/tasks/done.md" <<'EOF'
# Done Tasks
EOF
cat > "$BRAIN_PATH/wiki/log.md" <<'EOF'
# Log
EOF

brain-review-cycle --brain "$BRAIN_PATH" --dry-run --json > "$BRAIN_FACTORY_TMP/review-dry.json"
grep -q '"mode": "dry-run"' "$BRAIN_FACTORY_TMP/review-dry.json" || {
  echo "FAILED: dry-run json missing mode"
  cat "$BRAIN_FACTORY_TMP/review-dry.json"
  exit 1
}
find "$BRAIN_PATH/wiki" -maxdepth 1 -name 'review-cycle-*.md' | grep -q review-cycle || {
  echo "FAILED: dry-run did not write review report"
  exit 1
}
grep -q "^type: concept$" "$(find "$BRAIN_PATH/wiki" -maxdepth 1 -name 'review-cycle-*.md' | head -1)" || {
  echo "FAILED: review report missing wiki frontmatter"
  exit 1
}
grep -q "\\[\\[review-cycle-" "$BRAIN_PATH/wiki/review-cycles.md" || {
  echo "FAILED: review registry missing report link"
  cat "$BRAIN_PATH/wiki/review-cycles.md"
  exit 1
}
grep -q "\\[\\[review-cycles\\]\\]" "$BRAIN_PATH/wiki/index.md" || {
  echo "FAILED: wiki index missing review registry link"
  cat "$BRAIN_PATH/wiki/index.md"
  exit 1
}
! grep -q "Review corrective:" "$BRAIN_PATH/tasks/active.md" || {
  echo "FAILED: dry-run modified active tasks"
  cat "$BRAIN_PATH/tasks/active.md"
  exit 1
}

brain-review-cycle --brain "$BRAIN_PATH" --apply --agent codex-gpt5-review-cycle --json > "$BRAIN_FACTORY_TMP/review-apply.json"
grep -q '"mode": "apply"' "$BRAIN_FACTORY_TMP/review-apply.json" || {
  echo "FAILED: apply json missing mode"
  cat "$BRAIN_FACTORY_TMP/review-apply.json"
  exit 1
}
grep -q "Review corrective: replace TODO acceptance criteria" "$BRAIN_PATH/tasks/active.md" || {
  echo "FAILED: apply did not add acceptance corrective task"
  cat "$BRAIN_PATH/tasks/active.md"
  exit 1
}
grep -q "role: pm" "$BRAIN_PATH/tasks/active.md" || {
  echo "FAILED: corrective task missing pm role"
  cat "$BRAIN_PATH/tasks/active.md"
  exit 1
}
grep -q "acceptance: Active tasks listed in the linked review have concrete acceptance criteria" "$BRAIN_PATH/tasks/active.md" || {
  echo "FAILED: corrective task did not include concrete acceptance"
  cat "$BRAIN_PATH/tasks/active.md"
  exit 1
}
grep -q "ref: wiki/review-cycle-" "$BRAIN_PATH/tasks/active.md" || {
  echo "FAILED: corrective task should reference report by wiki path, not broken wikilink"
  cat "$BRAIN_PATH/tasks/active.md"
  exit 1
}
before_count=$(grep -c "Review corrective: replace TODO acceptance criteria" "$BRAIN_PATH/tasks/active.md")
brain-review-cycle --brain "$BRAIN_PATH" --apply --agent codex-gpt5-review-cycle --json > "$BRAIN_FACTORY_TMP/review-apply-2.json"
after_count=$(grep -c "Review corrective: replace TODO acceptance criteria" "$BRAIN_PATH/tasks/active.md")
[ "$before_count" = "$after_count" ] || {
  echo "FAILED: apply duplicated corrective task"
  cat "$BRAIN_PATH/tasks/active.md"
  exit 1
}

unit_dir="$BRAIN_FACTORY_TMP/systemd-user"
brain-review-cycle install-systemd --brain "$BRAIN_PATH" --unit-dir "$unit_dir" --no-enable --json > "$BRAIN_FACTORY_TMP/install.json"
test -f "$unit_dir/brain-review-cycle.service" || { echo "FAILED: service unit missing"; exit 1; }
test -f "$unit_dir/brain-review-cycle.timer" || { echo "FAILED: timer unit missing"; exit 1; }
grep -q "OnUnitActiveSec=3d" "$unit_dir/brain-review-cycle.timer" || {
  echo "FAILED: timer is not configured for 3-day cycle"
  cat "$unit_dir/brain-review-cycle.timer"
  exit 1
}
grep -q "^WorkingDirectory=$BRAIN_PATH$" "$unit_dir/brain-review-cycle.service" || {
  echo "FAILED: service WorkingDirectory must be an unquoted absolute path"
  cat "$unit_dir/brain-review-cycle.service"
  exit 1
}
grep -q "^Environment=\"BRAIN_PATH=$BRAIN_PATH\"$" "$unit_dir/brain-review-cycle.service" || {
  echo "FAILED: service Environment must quote the complete assignment"
  cat "$unit_dir/brain-review-cycle.service"
  exit 1
}
grep -q -- "--role reviewer" "$unit_dir/brain-review-cycle.service" || {
  echo "FAILED: service does not assign reviewer role"
  cat "$unit_dir/brain-review-cycle.service"
  exit 1
}
grep -q -- "--apply" "$unit_dir/brain-review-cycle.service" || {
  echo "FAILED: service does not apply corrective tasks"
  cat "$unit_dir/brain-review-cycle.service"
  exit 1
}

echo "review cycle automation OK"
