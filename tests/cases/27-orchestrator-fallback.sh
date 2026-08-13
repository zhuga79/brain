#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-orchestrator fallback on provider limits"

brain-orchestrator --help >/tmp/brain_orchestrator_help.txt
grep -q "fallback" /tmp/brain_orchestrator_help.txt || {
  echo "FAILED: brain-orchestrator help missing fallback"
  exit 1
}

fallback_marker="/tmp/brain_orchestrator_fallback_ran"
nonlimit_marker="/tmp/brain_orchestrator_nonlimit_fallback"
rm -f "$fallback_marker" "$nonlimit_marker"

brain-orchestrator run \
  --no-visible \
  --task t-smoke-limit \
  --agent smoke-primary \
  --to-role developer \
  --fallback "bash -lc 'echo fallback-ran > /tmp/brain_orchestrator_fallback_ran; exit 0'" \
  --dry-run \
  -- bash -lc 'echo "HTTP 429 Too Many Requests RESOURCE_EXHAUSTED" >&2; exit 42' \
  >/tmp/brain_orchestrator_dryrun.out
grep -q "DRY-RUN" /tmp/brain_orchestrator_dryrun.out || {
  echo "FAILED: dry-run output missing DRY-RUN"
  cat /tmp/brain_orchestrator_dryrun.out
  exit 1
}
[ ! -f "$fallback_marker" ] || {
  echo "FAILED: dry-run executed fallback"
  exit 1
}

if [ "${CODEX_SANDBOX_NETWORK_DISABLED:-}" = "1" ]; then
  if brain-orchestrator run \
    --no-visible \
    --task t-smoke-limit \
    --agent smoke-primary \
    --to-role developer \
    --fallback "bash -lc 'echo should-not-run > /tmp/brain_orchestrator_fallback_ran'" \
    -- bash -lc 'echo \"HTTP 429 Too Many Requests RESOURCE_EXHAUSTED\" >&2; exit 42' \
    >/tmp/brain_orchestrator_sandbox.out 2>/tmp/brain_orchestrator_sandbox.err; then
    echo "FAILED: orchestrator live run was allowed inside sandbox"
    exit 1
  fi
  grep -q "Refusing brain-orchestrator run inside sandbox" /tmp/brain_orchestrator_sandbox.err || {
    echo "FAILED: sandbox refusal did not explain run guard"
    cat /tmp/brain_orchestrator_sandbox.err
    exit 1
  }
  [ ! -f "$fallback_marker" ] || {
    echo "FAILED: sandbox refusal executed fallback"
    exit 1
  }
  echo "brain-orchestrator fallback OK (sandbox live launch refused)"
  exit 0
fi

fake_terminal="/tmp/brain_orchestrator_fake_terminal"
fake_terminal_args="/tmp/brain_orchestrator_fake_terminal_args"
cat > "$fake_terminal" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" > /tmp/brain_orchestrator_fake_terminal_args
exit 0
EOF
chmod +x "$fake_terminal"
DISPLAY=:99 BRAIN_ORCHESTRATOR_TERMINAL="$fake_terminal" brain-orchestrator run \
  --task t-smoke-visible \
  --agent smoke-primary \
  --to-role developer \
  -- bash -lc 'echo should-run-in-visible-window' \
  >/tmp/brain_orchestrator_visible.out 2>/tmp/brain_orchestrator_visible.err
grep -q "opened visible terminal" /tmp/brain_orchestrator_visible.out || {
  echo "FAILED: visible terminal launcher did not report launch"
  cat /tmp/brain_orchestrator_visible.out
  cat /tmp/brain_orchestrator_visible.err
  exit 1
}
grep -q "brain-orchestrator-visible" "$fake_terminal_args" || {
  echo "FAILED: fake terminal did not receive generated visible launcher"
  cat "$fake_terminal_args"
  exit 1
}
fake_terminal_wait="/tmp/brain_orchestrator_fake_terminal_wait"
cat > "$fake_terminal_wait" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" > /tmp/brain_orchestrator_fake_terminal_wait_args
exit 7
EOF
chmod +x "$fake_terminal_wait"
set +e
DISPLAY=:99 BRAIN_ORCHESTRATOR_TERMINAL="$fake_terminal_wait" brain-orchestrator run \
  --wait-visible \
  --task t-smoke-visible-wait \
  --agent smoke-primary \
  --to-role developer \
  -- bash -lc 'echo should-run-in-visible-window' \
  >/tmp/brain_orchestrator_visible_wait.out 2>/tmp/brain_orchestrator_visible_wait.err
visible_wait_rc=$?
set -e
[ "$visible_wait_rc" -eq 7 ] || {
  echo "FAILED: --wait-visible did not return terminal exit code ($visible_wait_rc)"
  cat /tmp/brain_orchestrator_visible_wait.out
  cat /tmp/brain_orchestrator_visible_wait.err
  exit 1
}
grep -q "opened visible terminal" /tmp/brain_orchestrator_visible_wait.out || {
  echo "FAILED: --wait-visible launcher did not report launch"
  cat /tmp/brain_orchestrator_visible_wait.out
  exit 1
}

brain-orchestrator run \
  --no-visible \
  --task t-smoke-limit \
  --agent smoke-primary \
  --to-role developer \
  --fallback "bash -lc 'echo fallback-ran > /tmp/brain_orchestrator_fallback_ran; exit 0'" \
  -- bash -lc 'echo "primary-visible-output"; echo "HTTP 429 Too Many Requests RESOURCE_EXHAUSTED" >&2; exit 42' \
  >/tmp/brain_orchestrator_limit.out 2>/tmp/brain_orchestrator_limit.err
grep -q "primary-visible-output" /tmp/brain_orchestrator_limit.out || {
  echo "FAILED: primary output was not streamed to orchestrator stdout"
  cat /tmp/brain_orchestrator_limit.out
  exit 1
}
grep -q "fallback-ran" "$fallback_marker" || {
  echo "FAILED: fallback command did not run after limit"
  cat /tmp/brain_orchestrator_limit.out
  cat /tmp/brain_orchestrator_limit.err
  exit 1
}
grep -q "limit detected" /tmp/brain_orchestrator_limit.err || {
  echo "FAILED: orchestrator did not report limit detection"
  cat /tmp/brain_orchestrator_limit.err
  exit 1
}
grep -q "fallback command succeeded" /tmp/brain_orchestrator_limit.err || {
  echo "FAILED: orchestrator did not report fallback success"
  cat /tmp/brain_orchestrator_limit.err
  exit 1
}
grep -q "reason: fallback" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || {
  echo "FAILED: fallback handoff artifact missing"
  exit 1
}
grep -q "provider_from" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || {
  echo "FAILED: handoff artifact missing provider_from"
  exit 1
}
grep -q "provider_to" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || {
  echo "FAILED: handoff artifact missing provider_to"
  exit 1
}
# Check journal for rank fields
last_journal=$(ls -t "$BRAIN_PATH"/handoff/journal-*.ndjson | head -n1)
grep -q '"rank"' "$last_journal" || {
  echo "FAILED: journal entry missing rank fields"
  exit 1
}
grep -q "Trigger Output Excerpt" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || {
  echo "FAILED: handoff artifact missing trigger excerpt"
  cat "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md"
  exit 1
}

rm -f "$fallback_marker"
brain-orchestrator run \
  --no-visible \
  --task t-smoke-large-limit \
  --agent smoke-primary \
  --to-role developer \
  --fallback "bash -lc 'echo fallback-ran > /tmp/brain_orchestrator_fallback_ran; exit 0'" \
  -- bash -lc 'python3 - <<'"'"'PY'"'"'
print("HTTP 429 Too Many Requests RESOURCE_EXHAUSTED")
print("A" * 2500000)
PY
exit 42' \
  >/tmp/brain_orchestrator_large_limit.out 2>/tmp/brain_orchestrator_large_limit.err
grep -q "fallback-ran" "$fallback_marker" || {
  echo "FAILED: fallback command did not run after large limit output"
  tail -n 40 /tmp/brain_orchestrator_large_limit.err
  exit 1
}
! grep -q "Argument list too long" /tmp/brain_orchestrator_large_limit.err || {
  echo "FAILED: large limit output leaked through argv"
  tail -n 40 /tmp/brain_orchestrator_large_limit.err
  exit 1
}
grep -q "reason: fallback" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || {
  echo "FAILED: large-output fallback handoff artifact missing"
  exit 1
}
grep -q "Trigger Output Excerpt" "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md" || {
  echo "FAILED: large-output handoff artifact missing trigger excerpt"
  exit 1
}
handoff_size=$(wc -c < "$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md")
[ "$handoff_size" -lt 200000 ] || {
  echo "FAILED: large-output handoff artifact was not bounded ($handoff_size bytes)"
  exit 1
}

rm -f "$fallback_marker"
brain-orchestrator run \
  --no-visible \
  --task t-smoke-capacity \
  --agent smoke-primary \
  --to-role developer \
  --fallback "bash -lc 'echo fallback-ran > /tmp/brain_orchestrator_fallback_ran; exit 0'" \
  -- bash -lc 'echo "MODEL_CAPACITY_EXHAUSTED: No capacity available for model" >&2; exit 42' \
  >/tmp/brain_orchestrator_capacity.out 2>/tmp/brain_orchestrator_capacity.err
grep -q "fallback-ran" "$fallback_marker" || {
  echo "FAILED: fallback command did not run after model capacity exhaustion"
  cat /tmp/brain_orchestrator_capacity.out
  cat /tmp/brain_orchestrator_capacity.err
  exit 1
}

rm -f "$fallback_marker"
brain-orchestrator run \
  --no-visible \
  --task t-smoke-usage-limit \
  --agent smoke-primary \
  --to-role developer \
  --fallback "bash -lc 'echo fallback-ran > /tmp/brain_orchestrator_fallback_ran; exit 0'" \
  -- bash -lc 'echo "ERROR: You have hit your usage limit. purchase more credits" >&2; exit 42' \
  >/tmp/brain_orchestrator_usage_limit.out 2>/tmp/brain_orchestrator_usage_limit.err
grep -q "fallback-ran" "$fallback_marker" || {
  echo "FAILED: fallback command did not run after Codex usage limit"
  cat /tmp/brain_orchestrator_usage_limit.out
  cat /tmp/brain_orchestrator_usage_limit.err
  exit 1
}

rm -f "$fallback_marker"
zero_task=$(brain-task add "Orchestrator Zero Exit Limit Task" --role developer --prio P1 | grep -oE "t-[0-9a-z-]+" | head -1)
brain-task take "$zero_task" --as smoke-zero-limit >/dev/null
brain-orchestrator run \
  --no-visible \
  --task "$zero_task" \
  --agent smoke-primary \
  --to-role developer \
  --fallback "bash -lc 'echo fallback-ran > /tmp/brain_orchestrator_fallback_ran; exit 0'" \
  -- bash -lc 'echo "MODEL_CAPACITY_EXHAUSTED: No capacity available for model"; exit 0' \
  >/tmp/brain_orchestrator_zero.out 2>/tmp/brain_orchestrator_zero.err
grep -q "fallback-ran" "$fallback_marker" || {
  echo "FAILED: fallback command did not run after zero-exit limit while task stayed active"
  cat /tmp/brain_orchestrator_zero.out
  cat /tmp/brain_orchestrator_zero.err
  exit 1
}
grep -q "limit output detected while task remains active" /tmp/brain_orchestrator_zero.err || {
  echo "FAILED: zero-exit limit fallback was not explained"
  cat /tmp/brain_orchestrator_zero.err
  exit 1
}
brain-task release "$zero_task" --as smoke-zero-limit >/dev/null

printf 'typed-command\n' | brain-orchestrator run \
  --no-visible \
  --pty \
  --task t-smoke-pty \
  --agent smoke-primary \
  --to-role developer \
  -- bash -lc 'printf "prompt>"; read line; echo "got:$line"' \
  >/tmp/brain_orchestrator_pty.out 2>/tmp/brain_orchestrator_pty.err
grep -q "prompt>" /tmp/brain_orchestrator_pty.out || {
  echo "FAILED: orchestrator PTY did not stream prompt"
  cat /tmp/brain_orchestrator_pty.out
  exit 1
}
grep -q "got:typed-command" /tmp/brain_orchestrator_pty.out || {
  echo "FAILED: orchestrator PTY did not forward stdin"
  cat /tmp/brain_orchestrator_pty.out
  exit 1
}

set +e
brain-orchestrator run \
  --no-visible \
  --task t-smoke-nonlimit \
  --agent smoke-primary \
  --to-role developer \
  --fallback "bash -lc 'echo should-not-run > /tmp/brain_orchestrator_nonlimit_fallback; exit 0'" \
  -- bash -lc 'echo "ordinary syntax failure" >&2; exit 33' \
  >/tmp/brain_orchestrator_nonlimit.out 2>/tmp/brain_orchestrator_nonlimit.err
nonlimit_rc=$?
set -e
[ "$nonlimit_rc" -eq 33 ] || {
  echo "FAILED: non-limit failure exit code not preserved: $nonlimit_rc"
  exit 1
}
[ ! -f "$nonlimit_marker" ] || {
  echo "FAILED: fallback ran for a non-limit failure"
  exit 1
}
grep -q "no limit pattern" /tmp/brain_orchestrator_nonlimit.err || {
  echo "FAILED: non-limit failure did not explain skipped fallback"
  cat /tmp/brain_orchestrator_nonlimit.err
  exit 1
}

echo "brain-orchestrator fallback OK"
