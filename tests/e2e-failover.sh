#!/usr/bin/env bash
# e2e-failover.sh — Brain orchestration failover drills
#
# Drills:
#   1. Stale-lock takeover  — Agent A holds lock past TTL; Agent B acquires it.
#   2. Dead-letter replay   — Webhook fails; dead-letter written; replay delivers.
#   3. Council-member abort — One opinion missing; arbiter synthesises partial data.
#
# Usage:
#   bash tests/e2e-failover.sh

set -euo pipefail

pass() { printf "[PASS] %s\n" "$*"; }
fail() { printf "[FAIL] %s\n" "$*" >&2; exit 1; }
section() { printf "\n=== Drill %s ===\n" "$*"; }

make_brain() {
  local dir
  dir="$(mktemp -d -t "failover-brain-XXXXXX")"
  mkdir -p "$dir"/{raw,wiki,tasks,roles,.locks,council}
  cat > "$dir/tasks/active.md" <<'EOF'
# Active tasks

> Брать СВЕРХУ. Внутри приоритета — сверху вниз.
> Перед изменением статуса — `brain-lock acquire <id> --as <agent-id>`.

## P0

## P1

## P2
EOF
  printf "# Done tasks\n" > "$dir/tasks/done.md"
  printf "" > "$dir/wiki/log.md"
  printf "# Index\n" > "$dir/wiki/index.md"
  printf "# Memory\n" > "$dir/MEMORY.md"
  echo "$dir"
}

# ── Drill 1: Stale-lock takeover ──────────────────────────────────────────────
section "1 — Stale-lock takeover"
# Expected: Agent A's lock expires after TTL=2s.
# Agent B can then acquire the same lock without manual intervention.
# This verifies that a crashed agent does not permanently block a task.

BRAIN_D1="$(make_brain)"
TASK_D1="t-failover-drill-1"
AGENT_A="agent-a-drill1"
AGENT_B="agent-b-drill1"

cat >> "$BRAIN_D1/tasks/active.md" <<EOF
- [ ] [P1] $TASK_D1 — Stale lock test
      role: developer   mode: solo
      acceptance: stale lock cleared
EOF

BRAIN_PATH="$BRAIN_D1" brain-lock acquire "$TASK_D1" --as "$AGENT_A" --ttl 2 >/dev/null 2>&1 \
  || fail "Drill 1: Agent A failed to acquire lock"
pass "Drill 1: Agent A acquired lock (TTL=2s)"
[ -d "$BRAIN_D1/.locks/$TASK_D1" ] || fail "Drill 1: lock dir missing"

sleep 3  # wait for TTL to expire

result="$(BRAIN_PATH="$BRAIN_D1" brain-lock acquire "$TASK_D1" --as "$AGENT_B" --json 2>&1)"
ok=$(echo "$result" | python3 -c "import json,sys; print(json.load(sys.stdin).get('ok',''))")
if [ "$ok" = "True" ]; then
  pass "Drill 1: Agent B acquired stale lock after TTL expiry"
else
  fail "Drill 1: Agent B could not acquire stale lock. Got: $result"
fi

BRAIN_PATH="$BRAIN_D1" brain-lock release "$TASK_D1" --as "$AGENT_B" >/dev/null 2>&1 || true
rm -rf "$BRAIN_D1"
pass "Drill 1: COMPLETE — stale-lock takeover verified"

# ── Drill 2: Dead-letter webhook replay ───────────────────────────────────────
section "2 — Dead-letter webhook replay"
# Expected: brain-task complete with unreachable webhook writes to dead-letter.
# After provider recovery (simulated with local HTTP server),
# brain-task webhook-replay delivers all queued entries and clears the file.

BRAIN_D2="$(make_brain)"
TASK_D2="t-failover-drill-2"

cat >> "$BRAIN_D2/tasks/active.md" <<EOF
- [~] [P1] $TASK_D2 — Webhook dead-letter test
      role: developer   mode: solo
      acceptance: dead-letter replay
      started: 2026-05-04T00:00:00Z
      by: drill2-agent
EOF

BRAIN_PATH="$BRAIN_D2" \
BRAIN_WEBHOOK_URL="http://127.0.0.1:29999/no-server" \
BRAIN_WEBHOOK_RETRIES=2 \
BRAIN_WEBHOOK_TIMEOUT_SEC=1 \
  brain-task complete "$TASK_D2" --as "drill2-agent" >/dev/null 2>&1 || true

DL_FILE="$BRAIN_D2/.webhooks/dead-letter.jsonl"
[ -f "$DL_FILE" ] || fail "Drill 2: dead-letter.jsonl not created after failed webhook"
DL_COUNT="$(grep -c . "$DL_FILE" 2>/dev/null || echo 0)"
[ "$DL_COUNT" -ge 1 ] || fail "Drill 2: dead-letter.jsonl is empty"
pass "Drill 2: dead-letter entry written (count=$DL_COUNT)"

# Replay against a running local server
BRAIN_PATH_D2="$BRAIN_D2" python3 - <<'PYEOF'
import http.server, json, os, pathlib, subprocess, threading, time

brain = os.environ["BRAIN_PATH_D2"]
received = []

class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        received.append(json.loads(self.rfile.read(n)))
        self.send_response(200); self.end_headers()
    def log_message(self, *a): pass

srv = http.server.HTTPServer(("127.0.0.1", 29998), H)
t = threading.Thread(target=srv.serve_forever); t.daemon = True; t.start()
time.sleep(0.2)

env = {**os.environ, "BRAIN_PATH": brain,
       "BRAIN_WEBHOOK_URL": "http://127.0.0.1:29998/hook"}
r = subprocess.run(["brain-task", "webhook-replay"], env=env, capture_output=True, text=True)
assert r.returncode == 0, f"replay failed: {r.stdout} {r.stderr}"
assert "replayed=1" in r.stdout, f"Expected replayed=1: {r.stdout}"
assert len(received) == 1, f"Server got {len(received)} requests, expected 1"
assert received[0]["event"] == "task-done", f"Wrong event: {received[0]}"

dl = pathlib.Path(brain, ".webhooks", "dead-letter.jsonl").read_text().strip()
assert dl == "", f"dead-letter not cleared after replay: {dl}"

srv.shutdown()
print("  replay: delivered and cleared dead-letter")
PYEOF

rm -rf "$BRAIN_D2"
pass "Drill 2: COMPLETE — dead-letter replay delivers and clears queue"

# ── Drill 3: Council-member abort (partial synthesis) ─────────────────────────
section "3 — Council-member abort (partial synthesis)"
# Expected: Council requires 3 opinions (architect, developer, reviewer).
# Developer agent aborts — no opinion file written.
# brain-council synthesize completes from the 2 available opinions,
# producing synthesis.md (partial opinions are sufficient for arbitration).

BRAIN_D3="$(make_brain)"
TASK_D3="t-failover-drill-3"

cat >> "$BRAIN_D3/tasks/active.md" <<EOF
- [ ] [P1] $TASK_D3 — Council abort drill
      role: architect   mode: council
      council: [architect, developer, reviewer]
      acceptance: partial synthesis
EOF

BRAIN_PATH="$BRAIN_D3" brain-council start "$TASK_D3" >/dev/null 2>&1 \
  || fail "Drill 3: brain-council start failed"
[ -d "$BRAIN_D3/council/$TASK_D3" ] || fail "Drill 3: council dir not created"
pass "Drill 3: council started"

cat > "$BRAIN_D3/council/$TASK_D3/architect.md" <<'EOF'
---
task: t-failover-drill-3
role: architect
agent: arch-drill3
model: claude-test
written: 2026-05-04T00:00:00Z
---

## Position
Use event-sourced design for the failover system.

## Reasoning
Event sourcing provides full audit trail and replay capability.

## Risks / Open questions
May add complexity for simple use cases.

## Recommendation
Adopt event sourcing with clear schema versioning.
EOF

cat > "$BRAIN_D3/council/$TASK_D3/reviewer.md" <<'EOF'
---
task: t-failover-drill-3
role: reviewer
agent: rev-drill3
model: gemini-test
written: 2026-05-04T00:00:00Z
---

## Position
Event sourcing is appropriate but start minimal.

## Reasoning
Full event sourcing upfront adds complexity prematurely.

## Risks / Open questions
Risk of over-engineering in early phases.

## Recommendation
Implement core events first; expand schema as requirements emerge.
EOF

# developer.md intentionally absent — simulating agent abort
pass "Drill 3: 2/3 opinions written (developer aborted)"

BRAIN_PATH="$BRAIN_D3" brain-council synthesize "$TASK_D3" >/dev/null 2>&1 \
  || fail "Drill 3: synthesize failed on partial opinions"

SYNTH="$BRAIN_D3/council/$TASK_D3/synthesis.md"
[ -f "$SYNTH" ] || fail "Drill 3: synthesis.md not created"
pass "Drill 3: synthesis.md created from partial opinions ($(wc -l < "$SYNTH") lines)"

rm -rf "$BRAIN_D3"
pass "Drill 3: COMPLETE — council synthesizes with partial opinions"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "  ALL FAILOVER DRILLS PASSED"
echo "=========================================="
