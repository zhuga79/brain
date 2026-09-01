#!/usr/bin/env bash
# Test: cyclic card "Запустить сейчас" + /api/cycle endpoint (whitelisted, mocked systemctl).
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying cyclic run-now button + /api/cycle endpoint"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
export PYTHONPATH="$PROJECT_ROOT/runtime/lib"

# 1) render: a cyclic card carries the run-now button wired to cycle-run
python3 - <<'PY'
from pathlib import Path
from brain_dashboard.render import html
status = {
    "scheduled": {"systemd_timers": {"items": [{"unit": "brain-provider-probe.timer", "next": "2026-05-30 16:20"}]}},
    "tasks": {"summary": {"active_count": 0, "done_count": 0, "states": {}, "priorities": {}, "roles": {}, "modes": {}}},
}
# Редизайн 73f18f2 заменил _render_board единым блоком _render_task_ops:
# циклы и автопилот теперь карточки внутри него.
out = html._render_task_ops([], [], {}, status, Path("/tmp/brain"))
assert "Запустить сейчас" in out, "run-now button missing"
assert "data-kb-action='cycle-run'" in out, "cycle-run wiring missing"
assert "data-kb-unit='brain-provider-probe.timer'" in out, "unit wiring missing"
print("OK: cyclic run-now button rendered")
PY

mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki" "$BRAIN_PATH/.brain"
printf '# Active Tasks\n' > "$BRAIN_PATH/tasks/active.md"
printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"

# 2) endpoint: mock systemctl so we never touch the real user units
shim="$BRAIN_FACTORY_TMP/shim"; mkdir -p "$shim"
cat > "$shim/systemctl" <<'SH'
#!/usr/bin/env bash
echo "mock systemctl $*"
exit 0
SH
chmod +x "$shim/systemctl"
export PATH="$shim:$PATH"

port=$(pick_free_port)
brain-dashboard serve --port "$port" &
srv_pid=$!
trap 'kill $srv_pid 2>/dev/null || true' EXIT
wait_dashboard_port "$port"

# valid brain unit + run -> ok
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:$port/api/cycle/brain-provider-probe.timer?action=run" | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert d.get('ok') is True, f'valid run should succeed: {d}'
assert d.get('action')=='run', d
print('OK: valid cycle run accepted')
" || { echo "FAILED: valid cycle run"; exit 1; }

# missing confirm header -> 403/false
curl -s --noproxy '*' -X POST "http://127.0.0.1:$port/api/cycle/brain-provider-probe.timer?action=run" | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert d.get('ok') is False and 'Confirm' in d.get('error',''), f'missing confirm should fail: {d}'
print('OK: confirm guard')
" || { echo "FAILED: confirm guard"; exit 1; }

# non-brain unit -> rejected (no arbitrary systemctl)
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:$port/api/cycle/evil.timer?action=run" | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert d.get('ok') is False and 'unit' in d.get('error','').lower(), f'non-brain unit should be rejected: {d}'
print('OK: unit whitelist enforced')
" || { echo "FAILED: unit whitelist"; exit 1; }

# unknown action -> 400
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:$port/api/cycle/brain-provider-probe.timer?action=destroy" | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert d.get('ok') is False and 'action' in d.get('error','').lower(), f'unknown action should fail: {d}'
print('OK: action validated')
" || { echo "FAILED: action validation"; exit 1; }

echo "dashboard cycle-run test PASSED"
