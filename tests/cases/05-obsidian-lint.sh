#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-lint --sync-report Obsidian views"
brain-lint --sync-report > /tmp/_lint_sync.log 2>&1 || { echo "FAILED: brain-lint --sync-report exited non-zero"; cat /tmp/_lint_sync.log; exit 1; }
grep -q "Obsidian views sync-report" /tmp/_lint_sync.log || { echo "FAILED: brain-lint --sync-report missing header"; cat /tmp/_lint_sync.log; exit 1; }
# Python unit test for obsidian_sync_report function
python3 - <<'PYEOF'
import sys, os, tempfile
from pathlib import Path
# __file__ == "<stdin>" в heredoc-скрипте — не путь к кейсу. Берём
# PROJECT_ROOT, который явно экспортирует раннер (tests/run.sh). Сейчас это
# маскируется тем, что PYTHONPATH уже содержит верный runtime/lib (см.
# tests/_lib.sh), но insert(0, ...) с битым путём — та же болезнь.
sys.path.insert(0, str(Path(os.environ["PROJECT_ROOT"]) / "runtime/lib"))
import brain_wiki

brain = Path(os.environ.get("BRAIN_PATH", str(Path.home() / "brain")))

# Run against real brain — views should be present (brain-index rebuild --with-obsidian runs in smoke)
report = brain_wiki.obsidian_sync_report(brain)
assert isinstance(report, dict), "obsidian_sync_report must return dict"
assert "ok" in report, "missing 'ok' key"
assert "views" in report, "missing 'views' key"
assert "missing" in report, "missing 'missing' key"
assert "message" in report, "missing 'message' key"
assert len(report["views"]) == len(brain_wiki.OBSIDIAN_EXPECTED_VIEWS), \
    f"Expected {len(brain_wiki.OBSIDIAN_EXPECTED_VIEWS)} views, got {len(report['views'])}"

# Test against empty tmp dir → all missing
with tempfile.TemporaryDirectory() as td:
    fake_brain = Path(td)
    r = brain_wiki.obsidian_sync_report(fake_brain)
    assert not r["ok"], "Should report not-ok for empty brain"
    assert len(r["missing"]) == len(brain_wiki.OBSIDIAN_EXPECTED_VIEWS), \
        f"Expected all missing, got: {r['missing']}"
    assert "WARN" in r["message"], f"Message should contain WARN: {r['message']}"

print("brain-lint sync-report OK")
PYEOF

cat > "$BRAIN_PATH/wiki/bad-source.md" <<EOF
---
title: Bad Source
type: concept
created: 2026-05-02
updated: 2026-05-02
curation: agent
protected: false
source_policy: advisory
tags: []
sources: [raw/missing.md]
related: []
---

# Bad Source
EOF
set +e
brain-validate > /tmp/brain_validate_bad_source.log 2>&1
bad_source_exit=$?
set -e
[ "$bad_source_exit" -ne 0 ] || { echo "FAILED: brain-validate should fail on missing source"; exit 1; }
grep -q "missing source raw/missing.md" /tmp/brain_validate_bad_source.log || { echo "FAILED: missing source not reported"; exit 1; }
rm -f "$BRAIN_PATH/wiki/bad-source.md"

cat > "$BRAIN_PATH/wiki/required-source.md" <<EOF
---
title: Required Source
type: concept
created: 2026-05-02
updated: 2026-05-02
curation: agent
protected: false
source_policy: required
tags: []
sources: []
related: []
---

# Required Source
EOF
set +e
brain-validate > /tmp/brain_validate_required_source.log 2>&1
required_source_exit=$?
set -e
[ "$required_source_exit" -ne 0 ] || { echo "FAILED: brain-validate should fail on source_policy required without sources"; exit 1; }
grep -q "source_policy=required" /tmp/brain_validate_required_source.log || { echo "FAILED: source_policy required not reported"; exit 1; }
rm -f "$BRAIN_PATH/wiki/required-source.md"

cat > "$BRAIN_PATH/wiki/bad-link.md" <<EOF
---
title: Bad Link
type: concept
created: 2026-05-02
updated: 2026-05-02
curation: agent
protected: false
source_policy: advisory
tags: []
sources: []
related: []
---

See [[missing-page]].
EOF
set +e
brain-validate > /tmp/brain_validate_bad_link.log 2>&1
bad_link_exit=$?
set -e
[ "$bad_link_exit" -ne 0 ] || { echo "FAILED: brain-validate should fail on missing wikilink"; exit 1; }
grep -q "broken wikilink \\[\\[missing-page\\]\\]" /tmp/brain_validate_bad_link.log || { echo "FAILED: missing wikilink not reported"; exit 1; }
rm -f "$BRAIN_PATH/wiki/bad-link.md"
brain-validate > /dev/null

