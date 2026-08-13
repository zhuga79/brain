#!/usr/bin/env bash
# case: bootstrap — Run setup scripts, verify executability/syntax
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

# This case expects the main brain to be installed already (by smoke.sh entry point)
# It only runs the bootstrap scripts and binary verification
run_bootstrap_scripts
verify_binaries

echo ">>> Verifying setup-brain-v2 is idempotent when BRAIN_PATH is the repo root"
# Проверяем на КОПИИ репозитория, а не на $PROJECT_ROOT. Раньше кейс запускал
# setup прямо по рабочему дереву: setup перезаписывает файлы, отличающиеся от
# шаблона, поэтому любая правка tasks/SCHEMA.md откатывалась при каждом полном
# прогоне тестов, а сам кейс лишь сообщал об этом постфактум.
repo_copy="$(mktemp -d)"
ALL_TMPDIRS+=("$repo_copy")
cp -r "$PROJECT_ROOT/setup-brain-v2.sh" "$PROJECT_ROOT/runtime" "$repo_copy/"

# Первый прогон разворачивает структуру, второй должен ничего не трогать.
BRAIN_PATH="$repo_copy" bash "$repo_copy/setup-brain-v2.sh" >/dev/null

schema_mtime_before="$(stat -c %y "$repo_copy/tasks/SCHEMA.md")"
BRAIN_PATH="$repo_copy" bash "$repo_copy/setup-brain-v2.sh" >"$repo_copy/setup.out"
grep -q "brain v2 path: $repo_copy" "$repo_copy/setup.out" || {
  echo "FAILED: setup did not run with repo root BRAIN_PATH"
  cat "$repo_copy/setup.out"
  exit 1
}
schema_mtime_after="$(stat -c %y "$repo_copy/tasks/SCHEMA.md")"
[ "$schema_mtime_before" = "$schema_mtime_after" ] || {
  echo "FAILED: setup touched unchanged tasks/SCHEMA.md"
  exit 1
}

# Рабочее дерево остаётся нетронутым — ради этого кейс и переписан.
[ -z "$(cd "$PROJECT_ROOT" && git status --porcelain tasks/SCHEMA.md)" ] || {
  echo "FAILED: bootstrap case modified the live tasks/SCHEMA.md"
  exit 1
}
