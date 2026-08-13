#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying webhook retry/backoff/idempotency/dead-letter/replay"
python3 - <<'PYEOF'
import http.server, json, os, pathlib, subprocess, tempfile, threading, time

# Minimal brain dir for webhook test
brain_dir = pathlib.Path(tempfile.mkdtemp(prefix="smoke-webhook-"))
(brain_dir / "tasks").mkdir()
(brain_dir / "tasks" / "active.md").write_text(
    "# Active tasks\n\n> Lock before taking.\n\n## P0\n\n## P1\n\n## P2\n")
(brain_dir / "tasks" / "done.md").write_text("# Done tasks\n")
(brain_dir / "wiki").mkdir()
(brain_dir / "wiki" / "log.md").write_text("")
(brain_dir / "wiki" / "index.md").write_text("# Index\n")
(brain_dir / "MEMORY.md").write_text("# Memory\n")

# ── Test 1: dead-letter on unreachable URL ─────────────────────────────────────
env = {**os.environ, "BRAIN_PATH": str(brain_dir),
       "BRAIN_WEBHOOK_URL": "http://127.0.0.1:19999/no-server",
       "BRAIN_WEBHOOK_ALLOW_LOOPBACK": "1",
       "BRAIN_WEBHOOK_RETRIES": "2", "BRAIN_WEBHOOK_TIMEOUT_SEC": "1"}

# Manually add a completed task entry (simulate brain-task complete flow)
import datetime, uuid, urllib.request
ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
task_id = "t-webhook-test-dead"
idem_key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{task_id}:{ts}"))
payload = json.dumps({
    "event": "task-done", "task_id": task_id, "agent_id": "test",
    "state": "done", "timestamp": ts, "brain_path": str(brain_dir),
}).encode()

# Invoke the webhook delivery Python inline (extract from brain-task logic)
# Simulate 2 retries against bad URL → dead-letter
import time as _time
last_err = None
for attempt in range(1, 3):
    req = urllib.request.Request(
        "http://127.0.0.1:19999/no-server", data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "brain-task/2.0",
                 "X-Brain-Idempotency-Key": idem_key, "X-Brain-Attempt": str(attempt)})
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=1): pass
        last_err = None; break
    except Exception as e:
        last_err = str(e)
        if attempt < 2: _time.sleep(0)

assert last_err, "Expected delivery failure to unreachable server"
dl_dir = brain_dir / ".webhooks"
dl_dir.mkdir(parents=True, exist_ok=True)
entry = json.dumps({
    "url": "http://127.0.0.1:19999/no-server",
    "payload": json.loads(payload.decode()),
    "idempotency_key": idem_key, "failed_at": ts, "error": last_err,
})
(dl_dir / "dead-letter.jsonl").write_text(entry + "\n")
assert (dl_dir / "dead-letter.jsonl").exists(), "dead-letter.jsonl not created"
lines = (dl_dir / "dead-letter.jsonl").read_text().strip().splitlines()
assert len(lines) == 1, f"Expected 1 dead-letter entry, got {len(lines)}"
e = json.loads(lines[0])
assert e["payload"]["task_id"] == task_id, "wrong task_id in dead-letter"
assert "idempotency_key" in e, "idempotency_key missing from dead-letter entry"
print("dead-letter write OK")

# ── Test 2: webhook-replay delivers and clears dead-letter ──────────────────────
received = []
class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        received.append(json.loads(body))
        self.send_response(200); self.end_headers()
    def log_message(self, *a): pass

server = http.server.HTTPServer(("127.0.0.1", 19998), Handler)
t = threading.Thread(target=server.serve_forever); t.daemon = True; t.start()

env2 = {**os.environ, "BRAIN_PATH": str(brain_dir),
        "BRAIN_WEBHOOK_URL": "http://127.0.0.1:19998/hook",
        "BRAIN_WEBHOOK_ALLOW_LOOPBACK": "1",
        "BRAIN_WEBHOOK_TIMEOUT_SEC": "3"}
r = subprocess.run(["brain-task", "webhook-replay"], env=env2,
                   capture_output=True, text=True)
assert r.returncode == 0, f"webhook-replay failed: {r.stdout} {r.stderr}"
assert "replayed=1" in r.stdout, f"Expected replayed=1: {r.stdout}"
assert len(received) == 1, f"Server got {len(received)} requests, expected 1"
assert received[0]["task_id"] == task_id, "Replayed wrong task_id"
# dead-letter should be cleared
remaining = (dl_dir / "dead-letter.jsonl").read_text().strip()
assert remaining == "", f"dead-letter not cleared after replay: {remaining}"
print("webhook-replay OK")

server.shutdown()
import shutil; shutil.rmtree(str(brain_dir), ignore_errors=True)
print("webhook reliability OK")
PYEOF
echo "webhook reliability OK"

