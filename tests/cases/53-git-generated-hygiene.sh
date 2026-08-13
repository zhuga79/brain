#!/usr/bin/env bash
# case: git-generated-hygiene
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying generated/local artifacts are not tracked"

bad_patterns=(
  '^\.brain/'
  '^\.coverage$'
  '^\.gemini/'
  '^\.gigaide/'
  '^\.idea/'
  '^\.policy/'
  '^\.vscode/'
  '^base\.md$'
  '^local\.md$'
  '^remote\.md$'
  '^merged\.md$'
  '^coverage_report\.txt$'
  '^test-limit\.json$'
  '^test-limit\.md$'
  '^test_cli\.sh$'
  '^wiki/stale-test\.md$'
  'local-command-caveatcaveat-the-messages-below\.txt$'
)

tracked="$(git -C "$PROJECT_ROOT" ls-files)"
for pattern in "${bad_patterns[@]}"; do
  if printf '%s\n' "$tracked" | grep -Eq "$pattern"; then
    printf 'FAILED: generated/local artifact is tracked: %s\n' "$pattern"
    printf '%s\n' "$tracked" | grep -E "$pattern" | sed -n '1,20p'
    exit 1
  fi
done

echo "git-generated-hygiene OK"
