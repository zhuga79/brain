#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-dashboard audit log"
# Static export: audit-log section present in HTML
brain-dashboard export > /dev/null
grep -q 'id="audit-log"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: audit-log section missing from dashboard export"; exit 1; }
grep -q 'Audit Log' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: Audit Log heading missing"; exit 1; }
grep -q 'wiki/log.md' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: wiki/log.md source reference missing"; exit 1; }
# Live HTTP: /api/audit endpoint
python3 - <<'PYEOF'
import sys, json, time, threading, socket, urllib.request, argparse
from pathlib import Path
import importlib.machinery, importlib.util, os
# __file__ == "<stdin>" в heredoc-скрипте — не путь к кейсу. Берём
# PROJECT_ROOT, который явно экспортирует раннер (tests/run.sh).
_project_root = Path(os.environ["PROJECT_ROOT"])
sys.path.insert(0, str(_project_root / "tests/lib"))
from wait_for_port import wait_for_port
src = _project_root / "runtime/bin/brain-dashboard"
loader = importlib.machinery.SourceFileLoader("brain_dashboard", str(src))
spec = importlib.util.spec_from_loader("brain_dashboard", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
brain = Path(os.environ.get("BRAIN_PATH", str(Path.home() / "brain")))
sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
args = argparse.Namespace(brain=str(brain), port=port)
t = threading.Thread(target=mod.cmd_serve, args=(args,), daemon=True); t.start()
# Ждём готовности сокета опросом, а не фиксированной паузой — см.
# tests/lib/wait_for_port.py. Прежний time.sleep(0.3) — предположение о
# скорости раннера, тот же класс, что уже уронил CI на двух других кейсах
# (t-2026-08-17-ci-flakes-block-the-recheck). Проверяемое свойство —
# доступность /api/audit, а не то, что сервер поднимается за 0.3с.
wait_for_port("127.0.0.1", port).close()
# Use no-proxy opener to avoid system HTTP_PROXY interfering with localhost
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def _get(url): return _opener.open(url, timeout=5)
# /api/audit returns JSON with entries list
resp = _get(f"http://127.0.0.1:{port}/api/audit")
d = json.loads(resp.read())
assert "entries" in d, f"Missing 'entries' in /api/audit: {d}"
assert "count" in d, f"Missing 'count' in /api/audit: {d}"
assert isinstance(d["entries"], list), f"'entries' should be list: {d}"
# Each entry has expected fields
if d["entries"]:
    e = d["entries"][0]
    for field in ("ts", "op", "task", "agent"):
        assert field in e, f"Missing field '{field}' in audit entry: {e}"
# /api/audit?task=<id> filters correctly
resp2 = _get(f"http://127.0.0.1:{port}/api/audit?task=nonexistent-xyz-999")
d2 = json.loads(resp2.read())
assert d2["count"] == 0, f"Filter by nonexistent task should return 0: {d2}"
print("/api/audit endpoint OK")
PYEOF

# read_audit_log unit test
python3 - <<'PYEOF'
import sys, os, tempfile
from pathlib import Path
# __file__ == "<stdin>" в heredoc-скрипте — не путь к кейсу. Берём
# PROJECT_ROOT, который явно экспортирует раннер (tests/run.sh).
_project_root = Path(os.environ["PROJECT_ROOT"])
sys.path.insert(0, str(_project_root / "runtime/lib"))
src = _project_root / "runtime/bin/brain-dashboard"
import importlib.machinery, importlib.util
loader = importlib.machinery.SourceFileLoader("brain_dashboard", str(src))
spec = importlib.util.spec_from_loader("brain_dashboard", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
brain = Path(os.environ.get("BRAIN_PATH", str(Path.home() / "brain")))
# Real log: should return entries
entries = mod.read_audit_log(brain, limit=5)
assert isinstance(entries, list), "read_audit_log should return list"
if entries:
    assert "ts" in entries[0] and "op" in entries[0], f"Missing fields: {entries[0]}"
    assert len(entries) <= 5, f"limit=5 exceeded: {len(entries)}"
# filter by task: should filter
task_ids = [e["task"] for e in entries if e["task"]]
if task_ids:
    filtered = mod.read_audit_log(brain, limit=20, task_filter=task_ids[0])
    assert all(task_ids[0] in e["task"] for e in filtered), "Filter did not work correctly"
# Empty brain: returns []
with tempfile.TemporaryDirectory() as td:
    assert mod.read_audit_log(Path(td)) == []
print("read_audit_log unit test OK")
PYEOF
echo "brain-dashboard audit log OK"
