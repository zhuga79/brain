#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-policy check"
brain-policy --help > /dev/null 2>&1 || { echo "FAILED: brain-policy --help"; exit 1; }
capture_output _bp_check 'brain-policy check 2>&1'
grep -q "All Brain workflow operations are accessible" <<< "$_bp_check" || {
  echo "FAILED: brain-policy check did not pass all gates"
  brain-policy check
  exit 1
}
echo "brain-policy check OK"

echo ">>> Verifying brain-release check (gate behavior)"
brain-release --help > /dev/null 2>&1 || { echo "FAILED: brain-release --help"; exit 1; }
# Use a temp repo with stub smoke.sh to avoid recursive smoke invocation
python3 - <<'PYEOF'
import subprocess, os, tempfile, pathlib, json, shutil, datetime, time

# Minimal valid brain (passes lint + validate)
brain_dir = pathlib.Path(tempfile.mkdtemp(prefix="smoke-relcheck-brain-"))
for d in ["raw", "tasks", "wiki/_views", ".locks", "roles"]:
    (brain_dir / d).mkdir(parents=True, exist_ok=True)
(brain_dir / "tasks" / "active.md").write_text(
    "# Active tasks\n\n> Lock before taking.\n\n## P0\n\n## P1\n\n## P2\n")
(brain_dir / "tasks" / "done.md").write_text("# Done tasks\n")
(brain_dir / "wiki" / "log.md").write_text("")
(brain_dir / "wiki" / "index.md").write_text("# Index\n")
(brain_dir / "MEMORY.md").write_text("# Memory\n")
(brain_dir / "roles" / "developer.md").write_text(
    "---\ntype: role\ndoctrine: []\nmodel_tier: fast\nwrites: [code]\n---\n# Developer\n")
# Роль без маршрута — дыра, на которую brain-validate теперь ругается:
# минимальный brain должен быть валидным, а не просто небольшим.
(brain_dir / "config").mkdir(parents=True, exist_ok=True)
(brain_dir / "config" / "routing.json").write_text(json.dumps({
    "version": 2, "defaults": {"cli": "claude"},
    "providers": {"claude": {"command": "claude", "model_flag": "--model {model}", "enabled": True}},
    "profiles": {"universal": [{"rank": 1, "provider": "claude", "model": "sonnet"}]},
    "roles": {"developer": {"profile": "universal"}},
}, ensure_ascii=False))
# Write manifest with per-file mtimes (no +60s hack needed after Phase 7 fix).
brain_idx = brain_dir / ".brain" / "index"
brain_idx.mkdir(parents=True, exist_ok=True)
files_map = {}
# Include wiki, raw, tasks as per new stale logic
for d in ["wiki", "raw", "tasks"]:
    for p in (brain_dir / d).glob("*.md"):
        if d == "wiki" and p.stem in ["index", "log"]:
            continue
        rel = str(p.relative_to(brain_dir))
        files_map[rel] = p.stat().st_mtime
now = datetime.datetime.now(datetime.timezone.utc)
(brain_idx / "manifest.json").write_text(json.dumps({
    "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "generated_epoch": now.timestamp(),
    "pages": 0, "raw": 0, "links": 0, "search_docs": 0,
    "files": files_map}))
for v in ["brain-pages.base", "brain-sources.base", "brain-decisions.base", "link-graph.canvas"]:
    (brain_dir / "wiki" / "_views" / v).write_text("")

# Minimal git repo with stub smoke.sh (avoids recursive invocation)
repo_dir = pathlib.Path(tempfile.mkdtemp(prefix="smoke-relcheck-repo-"))
subprocess.run(["git", "-C", str(repo_dir), "init", "-q"], check=True)
subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "t@t.com"], check=True)
subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "T"], check=True)
(repo_dir / "tests").mkdir()
(repo_dir / "tests" / "smoke.sh").write_text('#!/bin/bash\necho ">>> ALL TESTS PASSED"\n')
(repo_dir / "tests" / "smoke.sh").chmod(0o755)
(repo_dir / "readme.md").write_text("init")
subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
subprocess.run(["git", "-C", str(repo_dir), "commit", "-m", "init", "-q"], check=True)

env = {**os.environ, "BRAIN_PATH": str(brain_dir), "BRAIN_REPO_DIR": str(repo_dir)}
r = subprocess.run(["brain-release", "check"], env=env, capture_output=True, text=True)
output = r.stdout + r.stderr
assert "[OK]  brain-lint" in output, f"Missing brain-lint gate:\n{output[:600]}"
assert "[OK]  brain-validate" in output, f"Missing brain-validate gate:\n{output[:600]}"
assert "[OK]  index health" in output, f"Missing index health gate:\n{output[:600]}"
assert "gates passed" in output or "gate" in output, f"Missing results line:\n{output[:600]}"
print(f"brain-release check output OK (exit={r.returncode})")
shutil.rmtree(str(brain_dir), ignore_errors=True)
shutil.rmtree(str(repo_dir), ignore_errors=True)
PYEOF
echo "brain-release check OK"

echo ">>> Verifying brain-release tag gate (tag blocked when check fails)"
python3 - <<'PYEOF'
import subprocess, os, tempfile, pathlib, shutil, json

# Verify that brain-release tag blocks when brain-release check would fail.
# We test gate behavior using BRAIN_REPO_DIR with a fake repo that has active tasks.
# To avoid complex temp-brain setup, we test directly: check must exit non-zero
# when active>0, and tag rejects if check fails.

repo_dir = pathlib.Path(tempfile.mkdtemp(prefix="smoke-reltag-"))
brain_dir = pathlib.Path(tempfile.mkdtemp(prefix="smoke-reltag-brain-"))

# Minimal git repo
subprocess.run(["git", "-C", str(repo_dir), "init", "-q"], check=True)
subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "t@t.com"], check=True)
subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "T"], check=True)
(repo_dir / "tests").mkdir()
(repo_dir / "tests" / "smoke.sh").write_text('#!/bin/bash\necho ">>> ALL TESTS PASSED"\n')
(repo_dir / "tests" / "smoke.sh").chmod(0o755)
(repo_dir / "readme.md").write_text("init")
subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
subprocess.run(["git", "-C", str(repo_dir), "commit", "-m", "init", "-q"], check=True)

# Minimal valid brain with active task (brain-validate, brain-lint, brain-status must work)
for d in ["tasks", "wiki/_views", ".locks", "roles"]:
    (brain_dir / d).mkdir(parents=True, exist_ok=True)
(brain_dir / "tasks" / "active.md").write_text(
    "# Active tasks\n\n> Lock before taking.\n\n## P0\n\n## P1\n"
    "- [ ] [P1] t-fake-gate-test — Fake task\n      role: developer   mode: solo\n"
    "      acceptance: test gate\n\n## P2\n")
(brain_dir / "tasks" / "done.md").write_text("# Done tasks\n")
(brain_dir / "wiki" / "log.md").write_text("")
(brain_dir / "wiki" / "index.md").write_text("# Index\n")
(brain_dir / "MEMORY.md").write_text("# Memory\n")
(brain_dir / "roles" / "developer.md").write_text(
    "---\ntype: role\ndoctrine: []\nmodel_tier: fast\nwrites: [code]\n---\n# Developer\n")
# Роль без маршрута — дыра, на которую brain-validate теперь ругается:
# минимальный brain должен быть валидным, а не просто небольшим.
(brain_dir / "config").mkdir(parents=True, exist_ok=True)
(brain_dir / "config" / "routing.json").write_text(json.dumps({
    "version": 2, "defaults": {"cli": "claude"},
    "providers": {"claude": {"command": "claude", "model_flag": "--model {model}", "enabled": True}},
    "profiles": {"universal": [{"rank": 1, "provider": "claude", "model": "sonnet"}]},
    "roles": {"developer": {"profile": "universal"}},
}, ensure_ascii=False))
# brain-validate needs .brain/index/ with manifest
brain_idx = brain_dir / ".brain" / "index"
brain_idx.mkdir(parents=True, exist_ok=True)
(brain_idx / "manifest.json").write_text(json.dumps({
    "generated_at": "2026-05-04T00:00:00Z", "pages": 0, "raw": 0,
    "links": 0, "search_docs": 0
}))
# Obsidian views required by brain-validate
for v in ["brain-pages.base", "brain-sources.base", "brain-decisions.base", "link-graph.canvas"]:
    (brain_dir / "wiki" / "_views" / v).write_text("")

env = {**os.environ, "BRAIN_PATH": str(brain_dir), "BRAIN_REPO_DIR": str(repo_dir)}

# brain-release tag must fail (check gate: active=1 task remains)
r = subprocess.run(["brain-release", "tag", "v99", "--yes"],
                   env=env, capture_output=True, text=True)
assert r.returncode != 0, f"tag should be blocked when active>0, got exit 0:\n{r.stdout}"
assert "tasks remain" in r.stdout or "active=" in r.stdout, \
    f"Missing active gate message:\nSTDOUT: {r.stdout[:400]}\nSTDERR: {r.stderr[:200]}"

# Verify tag was NOT created
tags = subprocess.run(["git", "-C", str(repo_dir), "tag"],
                      capture_output=True, text=True).stdout
assert "v99" not in tags, f"Tag created despite gate failure: {tags}"

print("brain-release tag gate OK (blocked when active>0, tag not created)")
shutil.rmtree(str(repo_dir), ignore_errors=True)
shutil.rmtree(str(brain_dir), ignore_errors=True)
PYEOF
echo "brain-release tag gate OK"

echo ">>> Verifying BRAIN_RELEASE_CONFIG (custom version_regex)"
python3 - <<'PYEOF'
import subprocess, os, tempfile, pathlib, json, shutil, datetime

cfg = pathlib.Path(tempfile.mkstemp(prefix="release-cfg-", suffix=".json")[1])
cfg.write_text(json.dumps({"version_regex": r"^rel-\d+\.\d+\.\d+$"}))

repo_dir = pathlib.Path(tempfile.mkdtemp(prefix="smoke-relcfg-repo-"))
brain_dir = pathlib.Path(tempfile.mkdtemp(prefix="smoke-relcfg-brain-"))

subprocess.run(["git", "-C", str(repo_dir), "init", "-q"], check=True)
subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "t@t.com"], check=True)
subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "T"], check=True)
(repo_dir / "tests").mkdir()
(repo_dir / "tests" / "smoke.sh").write_text('#!/bin/bash\necho ">>> ALL TESTS PASSED"\n')
(repo_dir / "tests" / "smoke.sh").chmod(0o755)
(repo_dir / "readme.md").write_text("init")
subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
subprocess.run(["git", "-C", str(repo_dir), "commit", "-m", "init", "-q"], check=True)

for d in ["raw", "tasks", "wiki/_views", ".locks", "roles"]:
    (brain_dir / d).mkdir(parents=True, exist_ok=True)
(brain_dir / "tasks" / "active.md").write_text(
    "# Active tasks\n\n> Lock before taking.\n\n## P0\n\n## P1\n\n## P2\n")
(brain_dir / "tasks" / "done.md").write_text("# Done tasks\n")
(brain_dir / "wiki" / "log.md").write_text("")
(brain_dir / "wiki" / "index.md").write_text("# Index\n")
(brain_dir / "MEMORY.md").write_text("# Memory\n")
(brain_dir / "roles" / "developer.md").write_text(
    "---\ntype: role\ndoctrine: []\nmodel_tier: fast\nwrites: [code]\n---\n# Developer\n")
# Роль без маршрута — дыра, на которую brain-validate теперь ругается:
# минимальный brain должен быть валидным, а не просто небольшим.
(brain_dir / "config").mkdir(parents=True, exist_ok=True)
(brain_dir / "config" / "routing.json").write_text(json.dumps({
    "version": 2, "defaults": {"cli": "claude"},
    "providers": {"claude": {"command": "claude", "model_flag": "--model {model}", "enabled": True}},
    "profiles": {"universal": [{"rank": 1, "provider": "claude", "model": "sonnet"}]},
    "roles": {"developer": {"profile": "universal"}},
}, ensure_ascii=False))

brain_idx = brain_dir / ".brain" / "index"
brain_idx.mkdir(parents=True, exist_ok=True)
files_map = {}
for d in ["wiki", "raw", "tasks"]:
    for p in (brain_dir / d).glob("*.md"):
        if d == "wiki" and p.stem in ["index", "log"]:
            continue
        files_map[str(p.relative_to(brain_dir))] = p.stat().st_mtime
now = datetime.datetime.now(datetime.timezone.utc)
(brain_idx / "manifest.json").write_text(json.dumps({
    "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "generated_epoch": now.timestamp(),
    "pages": 0,
    "raw": 0,
    "links": 0,
    "search_docs": 0,
    "files": files_map,
}))
for v in ["brain-pages.base", "brain-sources.base", "brain-decisions.base", "brain-tasks.base", "link-graph.canvas"]:
    (brain_dir / "wiki" / "_views" / v).write_text("")

env = {
    **os.environ,
    "BRAIN_RELEASE_CONFIG": str(cfg),
    "BRAIN_PATH": str(brain_dir),
    "BRAIN_REPO_DIR": str(repo_dir),
}

# v6 must be REJECTED (doesn't match custom regex)
r = subprocess.run(["brain-release", "tag", "v6", "--yes"],
                   env=env, capture_output=True, text=True)
assert r.returncode != 0, f"v6 should be rejected by custom regex:\n{r.stdout}"
assert "rel-" in r.stderr or "rel-" in r.stdout, \
    f"Expected custom regex in error message:\nSTDOUT: {r.stdout[:200]}\nSTDERR: {r.stderr[:200]}"

# rel-1.2.3 must pass version validation (will fail later on git/repo, but regex passes)
r = subprocess.run(["brain-release", "tag", "rel-1.2.3", "--yes"],
                   env=env, capture_output=True, text=True)
combined = r.stdout + r.stderr
assert "version must match" not in combined, \
    f"rel-1.2.3 should pass custom regex:\n{combined[:400]}"
assert r.returncode == 0, f"rel-1.2.3 tag should pass in isolated repo:\n{combined[-800:]}"
tags = subprocess.run(["git", "-C", str(repo_dir), "tag"], capture_output=True, text=True).stdout
assert "rel-1.2.3" in tags, f"custom regex tag was not created: {tags}"

cfg.unlink()
shutil.rmtree(str(repo_dir), ignore_errors=True)
shutil.rmtree(str(brain_dir), ignore_errors=True)
print("BRAIN_RELEASE_CONFIG version_regex override OK")
PYEOF
echo "brain-release config OK"
