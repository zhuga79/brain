#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-federation merge-tasks"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

# 1. Setup base file
cat << 'EOF' > base.md
# Active tasks
- [ ] [P1] t-1 — Base Title
      role: developer
      acceptance: basic
EOF

# 2. Setup local file (change title and acceptance)
cat << 'EOF' > local.md
# Active tasks
- [ ] [P1] t-1 — Local Title
      role: developer
      acceptance: local-acceptance
EOF

# 3. Setup remote file (change state to in-progress)
cat << 'EOF' > remote.md
# Active tasks
- [~] [P1] t-1 — Base Title
      role: developer
      acceptance: basic
      started: 2026-05-13T12:00:00Z
      by: remote-agent
EOF

# 4. Run merge
python3 "$PROJECT_ROOT/runtime/bin/brain-federation" merge-tasks --base base.md --local local.md --remote remote.md --out merged.md

# 5. Verify merged content
# Should have Local Title AND in-progress state from remote
grep -q "\[~\] \[P1\] t-1 — Local Title" merged.md || { echo "FAILED: merge did not combine state and title correctly"; cat merged.md; exit 1; }
grep -q "acceptance: local-acceptance" merged.md || { echo "FAILED: merge did not keep local acceptance change"; exit 1; }
grep -q "by: remote-agent" merged.md || { echo "FAILED: merge lost remote metadata"; exit 1; }

echo "brain-federation merge-tasks OK"
