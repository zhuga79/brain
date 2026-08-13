#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying learning quality: dedupe / expiry / wiki conflict / prune"
python3 - <<'PYEOF'
import sys, os, tempfile, pathlib, subprocess, datetime, shutil
sys.path.insert(0, str(pathlib.Path.home() / ".local" / "lib" / "brain"))
from brain_learning import (
    ensure_dirs, write_lesson, transition_lesson,
    find_duplicate_active, is_expired, prune_expired_lessons,
    select_lessons_for_injection,
)

brain = pathlib.Path(tempfile.mkdtemp(prefix="smoke-quality-"))
ensure_dirs(brain)

# ── Duplicate gate ─────────────────────────────────────────────────────────────
les1 = {"rule": "Validate all external inputs before processing", "severity": "low",
        "roles": ["developer"], "status": "pending"}
write_lesson(brain, les1)
ok, _ = transition_lesson(brain, les1["id"], "active")
assert ok, "first activate should succeed"

les2 = {"rule": "Validate all external inputs before processing.", "severity": "low",
        "roles": ["developer"], "status": "pending"}
write_lesson(brain, les2)
ok, msg = transition_lesson(brain, les2["id"], "active")
assert not ok and "Duplicate" in msg, f"Expected duplicate block: {msg}"
print("duplicate gate OK")

# ── Expiry filter ──────────────────────────────────────────────────────────────
yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
les3 = {"rule": "Use async context managers for resources", "severity": "low",
        "roles": ["developer"], "status": "pending", "expires": yesterday}
write_lesson(brain, les3)
ok, _ = transition_lesson(brain, les3["id"], "active")
assert ok, "activate of lesson with past expiry should succeed"
inj = select_lessons_for_injection(brain, "developer")
assert les3["id"] not in [l["id"] for l in inj], "Expired lesson must not be injected"
assert les1["id"] in [l["id"] for l in inj], "Active non-expired lesson should be injected"
print("expiry injection filter OK")

# ── brain-learn quality-check CLI ─────────────────────────────────────────────
env = {**os.environ, "BRAIN_PATH": str(brain)}
r = subprocess.run(["brain-learn", "quality-check", "--id", les2["id"]],
                   env=env, capture_output=True, text=True)
assert r.returncode != 0, f"quality-check should flag duplicate (exit non-zero): {r.stdout}"
assert "duplicate" in r.stdout.lower(), f"Expected duplicate in output: {r.stdout}"
print("brain-learn quality-check CLI OK")

# ── brain-learn prune-expired CLI ─────────────────────────────────────────────
r = subprocess.run(["brain-learn", "prune-expired"],
                   env=env, capture_output=True, text=True)
assert r.returncode == 0, f"prune-expired failed: {r.stdout} {r.stderr}"
assert les3["id"] in r.stdout, f"Expected pruned id in output: {r.stdout}"
print("brain-learn prune-expired CLI OK")

shutil.rmtree(str(brain), ignore_errors=True)
print("learning quality OK")
PYEOF
echo "learning quality OK"
