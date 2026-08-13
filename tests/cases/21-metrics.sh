#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-dashboard /api/metrics endpoint"
python3 - <<'PYEOF'
import subprocess, os, tempfile, pathlib, json, time, urllib.request, shutil, signal

brain = pathlib.Path(tempfile.mkdtemp(prefix="smoke-metrics-"))
for d in ["tasks", "wiki", ".locks", "roles", "learning/incidents",
          "learning/lessons/active", "learning/lessons/pending"]:
    (brain / d).mkdir(parents=True, exist_ok=True)
(brain / "tasks" / "active.md").write_text(
    "# Active tasks\n\n> Lock before taking.\n\n## P0\n\n## P1\n\n## P2\n")
(brain / "tasks" / "done.md").write_text("# Done tasks\n")
(brain / "wiki" / "log.md").write_text("")
(brain / "wiki" / "index.md").write_text("# Index\n")
(brain / "MEMORY.md").write_text("# Memory\n")
(brain / ".brain" / "index").mkdir(parents=True, exist_ok=True)
(brain / ".brain" / "index" / "manifest.json").write_text(json.dumps({
    "generated_at": "2026-05-04T00:00:00Z", "pages": 0, "raw": 0,
    "links": 0, "search_docs": 0
}))
(brain / ".brain" / "token-metrics.jsonl").write_text(json.dumps({
    "ts": "2026-05-06T00:00:00Z",
    "kind": "test",
    "provider": "codex",
    "role": "developer",
    "session": "metrics-smoke",
    "raw_bytes": 400,
    "compact_bytes": 100,
    "raw_tokens_est": 100,
    "compact_tokens_est": 25,
    "savings_percent": 75,
    "raw_artifact": "/tmp/raw.log",
}) + "\n")
(brain / "wiki" / "_views").mkdir(parents=True, exist_ok=True)
for v in ["brain-pages.base", "brain-sources.base", "brain-decisions.base", "link-graph.canvas"]:
    (brain / "wiki" / "_views" / v).write_text("")

import socket as _sock
_s = _sock.socket(); _s.bind(("127.0.0.1", 0)); _port = _s.getsockname()[1]; _s.close()

env = {**os.environ, "BRAIN_PATH": str(brain)}
proc = subprocess.Popen(
    ["brain-dashboard", "serve", "--port", str(_port)],
    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
# Wait for server to be ready (retry up to 5s)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for _attempt in range(10):
    time.sleep(0.5)
    try:
        opener.open(f"http://127.0.0.1:{_port}/api/status", timeout=2)
        break
    except Exception:
        pass

try:
    resp = opener.open(f"http://127.0.0.1:{_port}/api/metrics", timeout=5)
    body = json.loads(resp.read())
    assert "generated_at" in body, f"Missing generated_at: {body}"
    assert "orchestration" in body, f"Missing orchestration: {body}"
    assert "learning" in body, f"Missing learning: {body}"
    assert "webhook" in body, f"Missing webhook: {body}"
    assert "policy" in body, f"Missing policy: {body}"
    assert "token_economy" in body, f"Missing token_economy: {body}"
    orch = body["orchestration"]
    assert "tasks_active" in orch and "tasks_done" in orch, f"orchestration fields missing: {orch}"
    lrn = body["learning"]
    assert "lessons_active" in lrn and "incidents" in lrn, f"learning fields missing: {lrn}"
    assert "dead_letter_count" in body["webhook"], f"webhook.dead_letter_count missing"
    pol = body["policy"]
    assert "status" in pol, f"policy.status missing: {pol}"
    assert pol["status"] == "unchecked", f"policy.status before check should be unchecked, got: {pol}"
    tok = body["token_economy"]
    assert tok["commands"] == 1, f"token_economy.commands missing: {tok}"
    assert tok["savings_percent"] == 75, f"token_economy savings wrong: {tok}"
    resp_tokens = opener.open(f"http://127.0.0.1:{_port}/api/tokens", timeout=5)
    token_body = json.loads(resp_tokens.read())
    assert token_body["recent"][0]["session"] == "metrics-smoke", token_body
    print(f"  /api/metrics schema OK: {list(body.keys())}, policy.status={pol['status']}")
finally:
    proc.terminate()
    proc.wait(timeout=5)

# Now run brain-policy check, expect /api/metrics.policy to update
import subprocess
r = subprocess.run(["brain-policy", "check"],
                   env={**os.environ, "BRAIN_PATH": str(brain)},
                   capture_output=True, text=True, timeout=15)
assert r.returncode == 0, f"brain-policy check failed: {r.stdout} {r.stderr}"

# Verify .policy/last-check.json written
policy_file = brain / ".policy" / "last-check.json"
assert policy_file.exists(), f"missing {policy_file}"

# Restart server, check policy block is now populated
_s2 = _sock.socket(); _s2.bind(("127.0.0.1", 0)); _port2 = _s2.getsockname()[1]; _s2.close()
proc2 = subprocess.Popen([sys.executable, "-m", "brain_dashboard_main"]
                          if False else
                          ["brain-dashboard", "serve", "--port", str(_port2)],
                          env={**os.environ, "BRAIN_PATH": str(brain)},
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(15):
        time.sleep(0.5)
        try:
            opener.open(f"http://127.0.0.1:{_port2}/api/status", timeout=2)
            break
        except Exception:
            pass
    resp = opener.open(f"http://127.0.0.1:{_port2}/api/metrics", timeout=5)
    body2 = json.loads(resp.read())
    pol2 = body2["policy"]
    assert pol2["status"] == "ok", f"policy.status after check should be ok, got: {pol2}"
    assert pol2["gates_passed"] >= 1, f"policy.gates_passed should be >=1: {pol2}"
    assert "last_run" in pol2 and pol2["last_run"], f"policy.last_run missing: {pol2}"
    print(f"  /api/metrics.policy after check: status={pol2['status']}, "
          f"gates_passed={pol2['gates_passed']}")
finally:
    proc2.terminate()
    proc2.wait(timeout=5)
    shutil.rmtree(str(brain), ignore_errors=True)
print("brain-dashboard /api/metrics OK")
PYEOF
echo "brain-dashboard /api/metrics OK"
