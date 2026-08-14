#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-workspace queue transactions under concurrency"

workspace_root="$(mktemp -d /tmp/brain-workspace-queue.XXXXXX)"
cat > "$workspace_root/BRAIN.md" <<'EOF'
# Workspace: Queue Transaction

available:
- developer
EOF

{
  echo "# Local Tasks"
  for i in $(seq 1 12); do
    printf '\n- [ ] [P1] local-%02d - Concurrent workspace task %02d\n' "$i" "$i"
    printf '      role: developer\n'
    printf '      acceptance: done\n'
  done
} > "$workspace_root/TASKS.md"
printf '# Local Log\n' > "$workspace_root/LOG.md"

pids=()
for i in $(seq 1 12); do
  tid=$(printf 'local-%02d' "$i")
  brain-workspace take --workspace "$workspace_root" "$tid" --as "agent-$i" >/dev/null 2>&1 &
  pids+=($!)
done

fail=0
for pid in "${pids[@]}"; do
  wait "$pid" || fail=1
done
[ "$fail" -eq 0 ] || { echo "FAILED: one or more concurrent take calls failed"; exit 1; }

for i in $(seq 1 12); do
  tid=$(printf 'local-%02d' "$i")
  grep -q -- "- \\[~\\] \\[P1\\] ${tid} - Concurrent workspace task $(printf '%02d' "$i")" "$workspace_root/TASKS.md" || {
    echo "FAILED: take lost state for $tid"
    exit 1
  }
  grep -q -- "by: agent-$i" "$workspace_root/TASKS.md" || {
    echo "FAILED: take lost owner for $tid"
    exit 1
  }
done

took_count=$(grep -c '^## .* | agent-.* | took local-' "$workspace_root/LOG.md" || true)
[ "$took_count" -eq 12 ] || { echo "FAILED: expected 12 take log entries, got $took_count"; exit 1; }

unset pids
declare -a pids=()
for i in $(seq 1 12); do
  tid=$(printf 'local-%02d' "$i")
  brain-workspace complete --workspace "$workspace_root" "$tid" --as "agent-$i" --model "openai-gpt-5.4" --summary "completed ${tid}" >/dev/null 2>&1 &
  pids+=($!)
done

fail=0
for pid in "${pids[@]}"; do
  wait "$pid" || fail=1
done
[ "$fail" -eq 0 ] || { echo "FAILED: one or more concurrent complete calls failed"; exit 1; }

for i in $(seq 1 12); do
  tid=$(printf 'local-%02d' "$i")
  grep -q -- "- \\[x\\] \\[P1\\] ${tid} - Concurrent workspace task $(printf '%02d' "$i")" "$workspace_root/TASKS.md" || {
    echo "FAILED: complete lost state for $tid"
    exit 1
  }
  grep -q -- "model: openai-gpt-5.4" "$workspace_root/TASKS.md" || {
    echo "FAILED: model signature missing after complete"
    exit 1
  }
done

completed_count=$(grep -c '^## .* | agent-.* | completed local-' "$workspace_root/LOG.md" || true)
[ "$completed_count" -eq 12 ] || { echo "FAILED: expected 12 complete log entries, got $completed_count"; exit 1; }

python3 - "$workspace_root/TASKS.md" "$workspace_root/LOG.md" "$PROJECT_ROOT/runtime/lib" <<'PY'
import sys
from pathlib import Path

tasks_path, log_path, libdir = sys.argv[1:]
sys.path.insert(0, libdir)
from brain_workspace import parse_local_log_entries, parse_local_tasks

tasks = parse_local_tasks(Path(tasks_path))
assert len(tasks) == 12, f"expected 12 tasks, got {len(tasks)}"
assert all(task.state == "done" for task in tasks), "not all tasks are done"

log_entries = parse_local_log_entries(Path(log_path), limit=64)
assert len(log_entries) >= 24, f"expected >=24 log entries, got {len(log_entries)}"
took = sum(1 for entry in log_entries if entry.summary.startswith("took local-"))
done = sum(1 for entry in log_entries if entry.summary.startswith("completed local-"))
assert took == 12, f"expected 12 take entries, got {took}"
assert done == 12, f"expected 12 complete entries, got {done}"
print("OK: workspace queue transitions and log entries survived concurrency")
PY

echo ">>> workspace queue transaction checks passed"
