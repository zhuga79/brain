#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-task webhook delivery"
python3 - "$PROJECT_ROOT/runtime/bin/brain-task" <<'PYEOF'
import sys, os, json, threading, socketserver, http.server, time, subprocess, tempfile, pathlib

task_src = sys.argv[1]

# Minimal mock HTTP server to receive webhook
received = []
class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        received.append(json.loads(body))
        self.send_response(200)
        self.end_headers()
    def log_message(self, *a): pass

with socketserver.TCPServer(("127.0.0.1", 0), Handler) as srv:
    port = srv.server_address[1]
    # Без паузы: TCPServer.__init__ делает bind()+listen() синхронно, до
    # возврата из конструктора — то есть до этой строки сокет уже слушает,
    # и ОС ставит входящие соединения в очередь backlog independent от того,
    # успел ли serve_forever() запуститься в потоке. Гонки «слушает ли порт»
    # здесь нет (в отличие от brain-dashboard serve, где bind() происходит
    # внутри самого запуска, а не в конструкторе) — проверено запуском:
    # t-2026-08-16-smoke-suite-cannot-run-concurr.
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()

    # Create a minimal brain for testing
    with tempfile.TemporaryDirectory() as td:
        brain = pathlib.Path(td) / "brain"
        brain.mkdir()
        (brain / "tasks").mkdir()
        (brain / "wiki").mkdir()
        (brain / ".locks").mkdir()
        # Write minimal active.md
        (brain / "tasks" / "active.md").write_text(
            "# Active\n\n- [ ] [P1] t-wh-test — Webhook test task\n"
        )
        (brain / "tasks" / "done.md").write_text("# Done\n\n")
        (brain / "wiki" / "log.md").write_text("")

        env = {**os.environ, "BRAIN_PATH": str(brain),
               "BRAIN_WEBHOOK_URL": f"http://127.0.0.1:{port}/hook",
               "BRAIN_WEBHOOK_TIMEOUT_SEC": "2",
               "BRAIN_WEBHOOK_ALLOW_LOOPBACK": "1",
               "PATH": os.environ["PATH"]}
        # Take the task first
        subprocess.run(["brain-task", "take", "t-wh-test", "--as", "smoke-webhook"],
                       env=env, capture_output=True)
        # Complete: should trigger webhook
        result = subprocess.run(["brain-task", "complete", "t-wh-test", "--as", "smoke-webhook",
                                 "--model", "openai-gpt-5.4"],
                                env=env, capture_output=True, text=True)
        assert result.returncode == 0, f"brain-task complete failed: {result.stderr}"
        assert "completed" in result.stdout, f"No 'completed' in output: {result.stdout}"
        time.sleep(0.3)

    srv.shutdown()

# Verify payload
assert received, "Webhook not called"
p = received[0]
assert p["event"] == "task-done", f"Wrong event: {p}"
assert p["task_id"] == "t-wh-test", f"Wrong task_id: {p}"
assert p["agent_id"] == "smoke-webhook", f"Wrong agent_id: {p}"
assert p["state"] == "done", f"Wrong state: {p}"
assert "timestamp" in p, f"Missing timestamp: {p}"
assert "brain_path" in p, f"Missing brain_path: {p}"
print("webhook delivery OK")

# Test safe-fail: network error does NOT break complete
with tempfile.TemporaryDirectory() as td:
    brain = pathlib.Path(td) / "brain"
    brain.mkdir()
    (brain / "tasks").mkdir()
    (brain / "wiki").mkdir()
    (brain / ".locks").mkdir()
    (brain / "tasks" / "active.md").write_text(
        "# Active\n\n- [ ] [P1] t-wh-fail — Webhook fail test\n"
    )
    (brain / "tasks" / "done.md").write_text("# Done\n\n")
    (brain / "wiki" / "log.md").write_text("")
    env = {**os.environ, "BRAIN_PATH": str(brain),
           "BRAIN_WEBHOOK_URL": "http://127.0.0.1:1/no-such-endpoint",
           "BRAIN_WEBHOOK_TIMEOUT_SEC": "1",
           "BRAIN_WEBHOOK_ALLOW_LOOPBACK": "1",
           "PATH": os.environ["PATH"]}
    subprocess.run(["brain-task", "take", "t-wh-fail", "--as", "smoke-agent"],
                   env=env, capture_output=True)
    result2 = subprocess.run(["brain-task", "complete", "t-wh-fail", "--as", "smoke-agent",
                              "--model", "openai-gpt-5.4"],
                             env=env, capture_output=True, text=True)
    assert result2.returncode == 0, f"complete failed when webhook unreachable: {result2.stderr}"
    assert "completed" in result2.stdout, f"No 'completed' when webhook fails: {result2.stdout}"
    print("webhook safe-fail OK")
PYEOF
echo "brain-task webhook OK"
