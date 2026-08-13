#!/usr/bin/env bash
# Smoke test for brain-launch --watch standalone mode.
# Tests the Python module directly with an empty/controlled brain dir.
# Does NOT run brain-launch --watch (infinite loop) in smoke.
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

_LIBPATH="$PROJECT_ROOT/runtime/lib"
_PY_FLAGS="PYTHONPATH=${_LIBPATH}:${HOME}/.local/lib/brain:${HOME}/.local/share/brain/lib${PYTHONPATH:+:${PYTHONPATH}}"

# Helper: create minimal brain structure in a temp dir
_mk_brain() {
  local td
  td=$(mktemp -d)
  mkdir -p "$td/tasks" "$td/wiki" "$td/.locks"
  printf "# Active\n\n" > "$td/tasks/active.md"
  printf "# Done\n\n" > "$td/tasks/done.md"
  printf "# Log\n\n" > "$td/wiki/log.md"
  echo "$td"
}

echo ">>> brain-launch --watch --exit-on-empty on empty queue (isolated brain)"
_tmp_brain=$(_mk_brain)
set +e
env PYTHONPATH="${_LIBPATH}:${HOME}/.local/lib/brain:${HOME}/.local/share/brain/lib${PYTHONPATH:+:${PYTHONPATH}}" \
  python3 -m brain_launch_watch "$_tmp_brain" "smoke-watch-$$" \
    --interval 1 \
    --exit-on-empty \
    > /tmp/brain_launch_watch_empty.log 2>&1
_rc=$?
set -e
rm -rf "$_tmp_brain"
[ "$_rc" -eq 0 ] || {
  echo "FAILED: --exit-on-empty on empty queue returned rc=$_rc"
  cat /tmp/brain_launch_watch_empty.log
  exit 1
}
grep -qi "queue empty\|no available\|exiting" /tmp/brain_launch_watch_empty.log || {
  echo "FAILED: expected exit message in output"
  cat /tmp/brain_launch_watch_empty.log
  exit 1
}
echo "brain-launch --watch --exit-on-empty (empty queue) OK"

echo ">>> brain-launch --watch --exit-on-empty with idle-limit (isolated brain)"
_tmp_brain2=$(_mk_brain)
set +e
env PYTHONPATH="${_LIBPATH}:${HOME}/.local/lib/brain:${HOME}/.local/share/brain/lib${PYTHONPATH:+:${PYTHONPATH}}" \
  python3 -m brain_launch_watch "$_tmp_brain2" "smoke-watch2-$$" \
    --interval 1 \
    --idle-limit 2 \
    > /tmp/brain_launch_watch_idle.log 2>&1
_rc2=$?
set -e
rm -rf "$_tmp_brain2"
[ "$_rc2" -eq 0 ] || {
  echo "FAILED: --idle-limit on empty queue returned rc=$_rc2"
  cat /tmp/brain_launch_watch_idle.log
  exit 1
}
grep -qi "idle limit\|idle round\|exiting" /tmp/brain_launch_watch_idle.log || {
  echo "FAILED: expected idle message in output"
  cat /tmp/brain_launch_watch_idle.log
  exit 1
}
echo "brain-launch --watch --idle-limit (empty queue) OK"

echo ">>> brain-launch --help shows new --watch flags"
brain-launch --help > /tmp/brain_launch_watch_help.log 2>&1 || true
grep -q "\-\-watch" /tmp/brain_launch_watch_help.log || {
  echo "FAILED: --watch not in --help output"
  cat /tmp/brain_launch_watch_help.log
  exit 1
}
grep -q "\-\-exit-on-empty" /tmp/brain_launch_watch_help.log || {
  echo "FAILED: --exit-on-empty not in --help output"
  cat /tmp/brain_launch_watch_help.log
  exit 1
}
grep -q "\-\-interval" /tmp/brain_launch_watch_help.log || {
  echo "FAILED: --interval not in --help output"
  cat /tmp/brain_launch_watch_help.log
  exit 1
}
echo "brain-launch --help shows new flags OK"

echo ">>> brain-launch --watch --role developer --exit-on-empty (role filter smoke)"
_tmp_brain3=$(_mk_brain)
set +e
env PYTHONPATH="${_LIBPATH}:${HOME}/.local/lib/brain:${HOME}/.local/share/brain/lib${PYTHONPATH:+:${PYTHONPATH}}" \
  python3 -m brain_launch_watch "$_tmp_brain3" "smoke-watch3-$$" \
    --role developer \
    --interval 1 \
    --exit-on-empty \
    > /tmp/brain_launch_watch_role.log 2>&1
_rc3=$?
set -e
rm -rf "$_tmp_brain3"
[ "$_rc3" -eq 0 ] || {
  echo "FAILED: --role developer --exit-on-empty returned rc=$_rc3"
  cat /tmp/brain_launch_watch_role.log
  exit 1
}
grep -qi "role filter\|developer\|queue empty\|exiting" /tmp/brain_launch_watch_role.log || {
  echo "FAILED: expected role filter or exit message"
  cat /tmp/brain_launch_watch_role.log
  exit 1
}
echo "brain-launch --watch --role developer --exit-on-empty OK"
