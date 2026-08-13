#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-learn --help and capture (human-edit)"
brain-learn --help > /dev/null 2>&1 || { echo "FAILED: brain-learn --help"; exit 1; }
echo "brain-learn --help OK"
python3 - <<'PYEOF'
import subprocess, os, tempfile, pathlib

brain_dir = pathlib.Path(tempfile.mkdtemp(prefix="smoke-learn-"))
env = {**os.environ, "BRAIN_PATH": str(brain_dir)}

r = subprocess.run(
    ["brain-learn", "capture", "t-smoke-task",
     "--source", "human-edit",
     "--role", "developer",
     "--model", "test-model",
     "--agent-id", "smoke-agent",
     "--severity", "low",
     "--tags", "smoke,testing",
     "--evidence", "Agent wrote wrong code",
     "--rule", "Always test before committing."],
    env=env, capture_output=True, text=True)
assert r.returncode == 0, f"capture failed: {r.stderr}"
assert "Created incident:" in r.stdout, f"No incident: {r.stdout}"
assert "Created pending lesson:" in r.stdout, f"No lesson: {r.stdout}"

r2 = subprocess.run(["brain-learn", "list"], env=env, capture_output=True, text=True)
assert r2.returncode == 0, f"list failed: {r2.stderr}"
assert "pending" in r2.stdout, f"No pending in list: {r2.stdout}"
assert "1 lesson" in r2.stdout, f"Wrong count: {r2.stdout}"

r3 = subprocess.run(["brain-learn", "list", "incidents"], env=env, capture_output=True, text=True)
assert r3.returncode == 0, f"list incidents failed: {r3.stderr}"
assert "human-edit" in r3.stdout, f"No human-edit: {r3.stdout}"
assert "t-smoke-task" in r3.stdout, f"No task_id: {r3.stdout}"

inc_id = [l.split(": ")[1].strip() for l in r.stdout.splitlines() if l.startswith("Created incident:")][0]
r4 = subprocess.run(["brain-learn", "show", inc_id], env=env, capture_output=True, text=True)
assert r4.returncode == 0, f"show failed: {r4.stderr}"
assert "source: human-edit" in r4.stdout, f"Missing source: {r4.stdout}"
assert "task_id: t-smoke-task" in r4.stdout, f"Missing task_id: {r4.stdout}"
assert "role: developer" in r4.stdout, f"Missing role: {r4.stdout}"
assert "model: test-model" in r4.stdout, f"Missing model: {r4.stdout}"
assert "Evidence" in r4.stdout, f"Missing evidence body: {r4.stdout}"
print("brain-learn human-edit capture OK")
PYEOF
echo "brain-learn capture (human-edit) OK"

echo ">>> Verifying brain-learn capture (auto-defects) and amend"
python3 - <<'PYEOF'
import subprocess, os, tempfile, pathlib

brain_dir = pathlib.Path(tempfile.mkdtemp(prefix="smoke-defects-"))
env = {**os.environ, "BRAIN_PATH": str(brain_dir)}

for source in ["smoke-failure", "lint-failure", "validate-failure", "runtime-error"]:
    r = subprocess.run(
        ["brain-learn", "capture",
         "--source", source,
         "--role", "developer",
         "--severity", "medium",
         "--evidence", f"Failure from {source}"],
        env=env, capture_output=True, text=True)
    assert r.returncode == 0, f"capture {source} failed: {r.stderr}"
    assert "Created incident:" in r.stdout, f"No incident for {source}: {r.stdout}"

    # Verify evidence is in incident body (not leaked to lesson body prompt)
    inc_id = [l.split(": ")[1].strip() for l in r.stdout.splitlines() if l.startswith("Created incident:")][0]
    r2 = subprocess.run(["brain-learn", "show", inc_id], env=env, capture_output=True, text=True)
    assert "Evidence" in r2.stdout, f"No evidence for {source}: {r2.stdout}"
    assert f"Failure from {source}" in r2.stdout, f"Evidence text missing for {source}"

    # Amend with root-cause and fix
    r3 = subprocess.run(
        ["brain-learn", "amend", inc_id,
         "--root-cause", f"Root cause of {source}",
         "--fix", f"Fixed {source} by updating tests"],
        env=env, capture_output=True, text=True)
    assert r3.returncode == 0, f"amend failed for {source}: {r3.stderr}"
    r4 = subprocess.run(["brain-learn", "show", inc_id], env=env, capture_output=True, text=True)
    assert "Root Cause" in r4.stdout, f"Root Cause not added for {source}"
    assert "Fix" in r4.stdout, f"Fix not added for {source}"

print("brain-learn auto-defect capture + amend OK (4 sources)")
PYEOF
echo "brain-learn capture (auto-defects) OK"

echo ">>> Verifying brain-learn lesson lifecycle (approve/reject/activate/deprecate)"
python3 - <<'PYEOF'
import subprocess, os, tempfile, pathlib

brain_dir = pathlib.Path(tempfile.mkdtemp(prefix="smoke-lifecycle-"))
env = {**os.environ, "BRAIN_PATH": str(brain_dir)}

def capture(source="smoke-failure", severity="low", rule="Test rule."):
    r = subprocess.run(
        ["brain-learn", "capture", "--source", source,
         "--severity", severity, "--rule", rule],
        env=env, capture_output=True, text=True)
    assert r.returncode == 0, f"capture failed: {r.stderr}"
    les_id = [l.split(": ")[1].strip() for l in r.stdout.splitlines() if l.startswith("Created pending lesson:")][0]
    return les_id

def run(cmd, expect_ok=True):
    r = subprocess.run(["brain-learn"] + cmd, env=env, capture_output=True, text=True)
    if expect_ok:
        assert r.returncode == 0, f"cmd {cmd} failed: {r.stderr}"
    else:
        assert r.returncode != 0, f"cmd {cmd} should have failed but didn't: {r.stdout}"
    return r

# --- Low severity: pending -> approved -> active -> deprecated
les = capture()
run(["approve", les, "--as", "smoke-arbiter"])
run(["activate", les])
r = run(["list", "--status", "active"])
assert les in r.stdout, f"Lesson not active: {r.stdout}"
run(["deprecate", les])
r = run(["list", "--status", "active"])
assert les not in r.stdout, f"Deprecated lesson still in active: {r.stdout}"

# --- Reject: pending -> rejected (not in active)
les2 = capture()
run(["reject", les2])
r = run(["list"])
assert les2 not in r.stdout, f"Rejected lesson in active list: {r.stdout}"

# --- High severity: must approve first, cannot activate directly
les_high = capture(severity="high", rule="High severity rule.")
run(["activate", les_high], expect_ok=False)   # must fail — not approved yet
run(["approve", les_high, "--as", "arbiter-agent"])
run(["activate", les_high])                     # now succeeds
r = run(["list", "--status", "active"])
assert les_high in r.stdout, f"High-severity lesson not active: {r.stdout}"

print("brain-learn lifecycle OK")
PYEOF
echo "brain-learn lifecycle (approve/reject/activate/deprecate) OK"

echo ">>> Verifying brain-run learning injection"
python3 - <<'PYEOF'
import subprocess, os, tempfile, pathlib, shutil

brain_dir = pathlib.Path(tempfile.mkdtemp(prefix="smoke-inject-"))
env = {**os.environ, "BRAIN_PATH": str(brain_dir)}

# Set up minimal brain structure
(brain_dir / "roles").mkdir()
(brain_dir / "roles" / "developer.md").write_text("# Developer role")
(brain_dir / "wiki").mkdir()
(brain_dir / "wiki" / "index.md").write_text("# Index")
(brain_dir / "MEMORY.md").write_text("# Memory")
(brain_dir / "tasks").mkdir()
(brain_dir / "tasks" / "active.md").write_text("# Active tasks\n")

# Create an active lesson for 'developer' role
r = subprocess.run(
    ["brain-learn", "capture", "--source", "smoke-failure",
     "--role", "developer", "--severity", "low",
     "--rule", "Always bypass HTTP proxy in test socket calls."],
    env=env, capture_output=True, text=True)
assert r.returncode == 0, f"capture: {r.stderr}"
les_id = [l.split(": ")[1].strip() for l in r.stdout.splitlines() if l.startswith("Created pending lesson:")][0]
subprocess.run(["brain-learn", "approve", les_id, "--as", "smoke-agent"], env=env, check=True)
subprocess.run(["brain-learn", "activate", les_id], env=env, check=True)

# Run brain-run and check injection block appears
brain_run = pathlib.Path(os.environ["PATH"].split(":")[0]).parent / "bin" / "brain-run"
# Find brain-run in PATH
brain_run_path = subprocess.run(["which", "brain-run"], capture_output=True, text=True).stdout.strip()
r2 = subprocess.run([brain_run_path, "--role", "developer"], env=env, capture_output=True, text=True)
assert r2.returncode == 0, f"brain-run failed: {r2.stderr}"
assert "LEARNED LESSONS" in r2.stdout, f"No injection block in brain-run output: {r2.stdout[:500]}"
assert "bypass HTTP proxy" in r2.stdout, f"Lesson rule not in output: {r2.stdout[:500]}"

# Lesson for non-matching role should NOT appear
r3 = subprocess.run([brain_run_path, "--role", "developer"], env=env, capture_output=True, text=True)
# Inject a reviewer lesson and verify it doesn't appear for developer
r4 = subprocess.run(
    ["brain-learn", "capture", "--source", "smoke-failure",
     "--role", "reviewer", "--severity", "low",
     "--rule", "Reviewer-only rule that should not appear for developer."],
    env=env, capture_output=True, text=True)
rev_les = [l.split(": ")[1].strip() for l in r4.stdout.splitlines() if l.startswith("Created pending lesson:")][0]
subprocess.run(["brain-learn", "approve", rev_les, "--as", "a"], env=env, check=True)
subprocess.run(["brain-learn", "activate", rev_les], env=env, check=True)

r5 = subprocess.run([brain_run_path, "--role", "developer"], env=env, capture_output=True, text=True)
assert "Reviewer-only rule" not in r5.stdout, f"Reviewer lesson leaked into developer prompt: {r5.stdout[:500]}"

print("brain-run injection OK (lessons injected, role-filtered)")
PYEOF
echo "brain-run learning injection OK"

echo ">>> Verifying brain-learn phase-capture"
python3 - <<'PYEOF'
import subprocess, os, tempfile, pathlib

brain_dir = pathlib.Path(tempfile.mkdtemp(prefix="smoke-phase-"))
repo_dir = pathlib.Path(tempfile.mkdtemp(prefix="smoke-repo-"))
env = {**os.environ, "BRAIN_PATH": str(brain_dir), "BRAIN_REPO_DIR": str(repo_dir)}

# Init a minimal git repo with a fixing commit
subprocess.run(["git", "-C", str(repo_dir), "init", "-q"], check=True)
subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "test@test.com"], check=True)
subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "Test"], check=True)
(repo_dir / "readme.md").write_text("init")
subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
subprocess.run(["git", "-C", str(repo_dir), "commit", "-m", "init", "-q"], check=True)
(repo_dir / "fix_smoke.py").write_text("# fix smoke test proxy issue")
subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
subprocess.run(["git", "-C", str(repo_dir), "commit", "-m", "fix: bypass proxy in smoke test", "-q"], check=True)

r = subprocess.run(
    ["brain-learn", "phase-capture", "--phase", "phase5"],
    env=env, capture_output=True, text=True)
assert r.returncode == 0, f"phase-capture failed: {r.stderr}\n{r.stdout}"
assert "pending lesson" in r.stdout.lower() or "0 pending" in r.stdout, f"Unexpected output: {r.stdout}"
assert "No lessons were activated" in r.stdout, f"Should state no activation: {r.stdout}"

# Verify lessons are pending (not active)
r2 = subprocess.run(["brain-learn", "list", "--pending"], env=env, capture_output=True, text=True)
assert r2.returncode == 0, f"list --pending failed: {r2.stderr}"
# Should have some pending lessons or 0 (if no matching commits found)
print(f"phase-capture output: {r.stdout.strip()}")
print("brain-learn phase-capture OK")
PYEOF
echo "brain-learn phase-capture OK"
