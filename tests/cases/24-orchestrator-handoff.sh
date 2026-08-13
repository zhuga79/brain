#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-handoff create/show"
brain-task add "Handoff Next Task" --role developer --prio P1 >/dev/null
brain-handoff create --reason manual --from smoke-orchestrator --to-role developer >/tmp/brain_handoff_create.log
grep -q "handoff:" /tmp/brain_handoff_create.log || { echo "FAILED: create did not print handoff path"; exit 1; }
[ -f "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" ] || { echo "FAILED: handoff artifact missing"; exit 1; }
grep -q "reason: manual" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: handoff reason missing"; exit 1; }
grep -q "from_agent: smoke-orchestrator" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: handoff from_agent missing"; exit 1; }
grep -q "brain-task take" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: handoff next commands missing"; exit 1; }
brain-handoff show >/tmp/brain_handoff_show.log
grep -q "Brain Orchestrator Handoff" /tmp/brain_handoff_show.log || { echo "FAILED: show did not print handoff"; exit 1; }

echo ">>> Verifying brain-handoff JSON output"
brain-handoff create --reason manual --from smoke-orchestrator --to-role developer --json >/tmp/brain_handoff_create.json
python3 - <<'PYEOF'
import json, pathlib
data = json.load(open("/tmp/brain_handoff_create.json"))
assert data["ok"] is True, data
assert data["schema_version"] == 1, data
assert data["artifact"]["reason"] == "manual", data
assert data["artifact"]["from_agent"] == "smoke-orchestrator", data
assert data["artifact"]["to_role"] == "developer", data
assert data["artifact"]["path"], data
assert pathlib.Path(data["artifact"]["path"]).exists(), data
assert any("brain-task list" in cmd for cmd in data["artifact"]["commands"]), data
assert isinstance(data["artifact"]["provider_summary"], list), data
assert "status_text" in data["artifact"], data
PYEOF
brain-handoff show --json >/tmp/brain_handoff_show.json
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_handoff_show.json"))
assert data["ok"] is True, data
assert data["schema_version"] == 1, data
artifact = data["artifact"]
assert artifact["exists"] is True, artifact
assert artifact["reason"] == "manual", artifact
assert artifact["from_agent"] == "smoke-orchestrator", artifact
assert any("brain-task list" in cmd for cmd in artifact["commands"]), artifact
assert isinstance(artifact["provider_summary"], list), artifact
assert isinstance(artifact["active_queue_excerpt"], str), artifact
PYEOF

echo ">>> Verifying handoff continues the current in-progress task"
current_task=$(brain-task add "Handoff Current Task" --role developer --prio P1 | grep -oE "t-[0-9a-z-]+" | head -1)
brain-task take "$current_task" --as smoke-current >/dev/null
brain-handoff create --reason limit-exhausted --from smoke-current --to-role developer --task "$current_task" >/tmp/brain_handoff_current.log
grep -q "task: $current_task" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: handoff current task field missing"; exit 1; }
grep -q "brain-run --role developer --task $current_task" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || {
  echo "FAILED: handoff does not provide command to continue current task"
  cat "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md"
  exit 1
}
brain-task release "$current_task" --as smoke-current >/dev/null

echo ">>> Verifying brain-handoff run creates handoff on limit failure"
set +e
brain-handoff run --task t-smoke-limit --agent smoke-orchestrator --to-role developer -- bash -lc 'echo "HTTP 429 Too Many Requests RESOURCE_EXHAUSTED" >&2; exit 42' >/tmp/brain_handoff_run.out 2>/tmp/brain_handoff_run.err
handoff_rc=$?
set -e
[ "$handoff_rc" -eq 42 ] || { echo "FAILED: run did not preserve exit code ($handoff_rc)"; exit 1; }
grep -q "limit detected" /tmp/brain_handoff_run.err || { echo "FAILED: run did not report limit handoff"; cat /tmp/brain_handoff_run.err; exit 1; }
grep -q "reason: limit-exhausted" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: limit handoff reason missing"; exit 1; }
grep -q "Trigger Output Excerpt" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: limit output excerpt missing"; exit 1; }
grep -q "orchestrator-handoff" "$BRAIN_PATH/wiki/log.md" || { echo "FAILED: handoff log entry missing"; exit 1; }
echo "brain-handoff limit handoff OK"

echo ">>> Verifying brain-handoff PTY passthrough and zero-exit limit output"
printf 'typed-command\n' | brain-handoff run --pty --task t-smoke-pty --agent smoke-orchestrator --to-role developer -- bash -lc 'printf "prompt>"; read line; echo "got:$line"' >/tmp/brain_handoff_pty.out 2>/tmp/brain_handoff_pty.err
grep -q "prompt>" /tmp/brain_handoff_pty.out || { echo "FAILED: PTY prompt was not streamed immediately"; cat /tmp/brain_handoff_pty.out; exit 1; }
grep -q "got:typed-command" /tmp/brain_handoff_pty.out || { echo "FAILED: PTY stdin was not forwarded"; cat /tmp/brain_handoff_pty.out; exit 1; }

zero_task=$(brain-task add "Handoff Zero Exit Limit Task" --role developer --prio P1 | grep -oE "t-[0-9a-z-]+" | head -1)
brain-task take "$zero_task" --as smoke-zero-limit >/dev/null
brain-handoff run --task "$zero_task" --agent smoke-zero-limit --to-role developer -- bash -lc 'echo "MODEL_CAPACITY_EXHAUSTED: No capacity available for model"; exit 0' >/tmp/brain_handoff_zero.out 2>/tmp/brain_handoff_zero.err
grep -q "limit detected" /tmp/brain_handoff_zero.err || { echo "FAILED: zero-exit limit output did not create handoff"; cat /tmp/brain_handoff_zero.err; exit 1; }
grep -q "brain-run --role developer --task $zero_task" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || { echo "FAILED: zero-exit limit handoff does not continue active task"; cat "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md"; exit 1; }
brain-task release "$zero_task" --as smoke-zero-limit >/dev/null
echo "brain-handoff PTY and zero-exit limit OK"
