#!/usr/bin/env bash
# Test: brain_core.taskfile serializes concurrent writers to tasks/active.md
# and tasks/done.md so 20 agents completing 20 *different* tasks at once
# never lose a task. Before t-2026-08-10-core-atomic-taskfile, brain-task
# take/release/complete/block did read-whole-file -> regex -> write-whole-file
# with no lock around the critical section: the lock protocol protects a
# *task*, not the file, so two agents finishing different tasks raced on the
# same active.md/done.md and the writer that finished second silently
# discarded the first one's edit. See wiki/decision-runtime-core-boundaries.md.
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-task complete under 20-way concurrency loses no task"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki"

N=20
{
  echo "# Active Tasks"
  for i in $(seq 1 "$N"); do
    printf '\n- [ ] [P2] t-concurrent-%02d — Concurrent complete %02d\n' "$i" "$i"
    printf '      role: developer   mode: solo\n'
    printf '      acceptance: ok\n'
  done
} > "$BRAIN_PATH/tasks/active.md"
printf '# Done Tasks\n' > "$BRAIN_PATH/tasks/done.md"
printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"

pids=()
for i in $(seq 1 "$N"); do
  tid=$(printf 't-concurrent-%02d' "$i")
  brain-task complete "$tid" --as "agent-$i" --model "test-model" >/dev/null 2>&1 &
  pids+=($!)
done

fail=0
for pid in "${pids[@]}"; do
  wait "$pid" || fail=1
done
[ "$fail" -eq 0 ] || { echo "FAILED: one or more brain-task complete calls exited non-zero"; exit 1; }

# Every task must have moved to done.md exactly once, and none left behind
# in active.md — grep-level check first (cheap, gives a readable diagnosis).
missing=0
dup=0
for i in $(seq 1 "$N"); do
  tid=$(printf 't-concurrent-%02d' "$i")
  count_done=$(grep -c -- "- \[x\].*${tid} —" "$BRAIN_PATH/tasks/done.md" || true)
  if [ "$count_done" -ne 1 ]; then
    echo "MISMATCH in done.md: $tid appears $count_done time(s)"
    if [ "$count_done" -eq 0 ]; then missing=$((missing + 1)); else dup=$((dup + 1)); fi
  fi
  if grep -q -- "${tid} —" "$BRAIN_PATH/tasks/active.md"; then
    echo "STILL IN active.md: $tid"
    missing=$((missing + 1))
  fi
done
if [ "$missing" -ne 0 ] || [ "$dup" -ne 0 ]; then
  echo "FAILED: $missing missing/left-behind, $dup duplicated — lost update under concurrency"
  exit 1
fi
echo "OK: all $N tasks completed exactly once, none lost"

# Parse-level sanity: confirm done.md is still a well-formed task file (no
# blocks truncated mid-write by an overlapping writer) and active.md has no
# leftover task blocks at all.
python3 - "$BRAIN_PATH/tasks/done.md" "$BRAIN_PATH/tasks/active.md" "$N" "$PROJECT_ROOT/runtime/lib" <<'PY'
import sys
done_path, active_path, n, libdir = sys.argv[1:]
sys.path.insert(0, libdir)
import brain_task_parser

n = int(n)
done_text = open(done_path, encoding="utf-8").read()
active_text = open(active_path, encoding="utf-8").read()

done_blocks = brain_task_parser.find_blocks(done_text)
ids = set()
for block in done_blocks:
    info = brain_task_parser.parse_block(block)
    if not info:
        print(f"FAILED: unparsable block in done.md: {block[:80]!r}")
        sys.exit(1)
    ids.add(info["id"])

expected = {f"t-concurrent-{i:02d}" for i in range(1, n + 1)}
missing_ids = expected - ids
if missing_ids:
    print(f"FAILED: done.md missing ids after parse: {sorted(missing_ids)}")
    sys.exit(1)
if len(done_blocks) != n:
    print(f"FAILED: expected {n} blocks in done.md, found {len(done_blocks)}")
    sys.exit(1)

active_blocks = brain_task_parser.find_blocks(active_text)
if active_blocks:
    print(f"FAILED: {len(active_blocks)} task block(s) still left in active.md")
    sys.exit(1)

print(f"OK: done.md well-formed, {len(done_blocks)} blocks parsed; active.md has no leftover blocks")
PY

echo ">>> taskfile concurrent complete checks passed"
