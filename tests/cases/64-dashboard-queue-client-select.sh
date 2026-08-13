#!/usr/bin/env bash
# Test: per-proposal CLI/provider dropdown in Queue Autopilot + launch client override.
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying per-proposal CLI/provider dropdown + client override"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
export PYTHONPATH="$PROJECT_ROOT/runtime/lib"

mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki" "$BRAIN_PATH/roles" "$BRAIN_PATH/.brain/launch-queue"
# Предложение автопилота теперь висит на карточке задачи, поэтому задача
# должна существовать: предложение без задачи в новой вёрстке бессмысленно.
cat > "$BRAIN_PATH/tasks/active.md" <<'TASKS'
# Active Tasks

- [ ] [P1] t-2026-05-29-test — Client select
      role: developer   mode: solo
TASKS
printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"
printf '# Developer\n' > "$BRAIN_PATH/roles/developer.md"
# Global-queue proposal (workspace empty -> dry-run console needs no BRAIN.md)
cat > "$BRAIN_PATH/.brain/launch-queue/proposals.json" <<'JSON'
{
  "ok": true,
  "proposals": [
    {"id": "qp-test-cli", "status": "pending", "task": "t-2026-05-29-test", "title": "Client select",
     "role": "developer", "client": "codex", "workspace": ""}
  ]
}
JSON

# (a) Rendered HTML carries the per-proposal select with options.
brain-dashboard export > /dev/null
HTML="$BRAIN_PATH/wiki/_views/brain-dashboard.html"
# Редизайн 73f18f2 убрал отдельный выпадающий список на каждое предложение:
# клиент выбирается в панели «Ручной запуск» вкладки, а предложение
# привязано к карточке задачи. Проверяем то, что осталось, — привязку
# предложения и наличие выбора клиента; переопределение клиента при запуске
# проверяется ниже через API, где оно и живёт.
grep -q "data-kb-proposal='qp-test-cli'" "$HTML" || { echo "FAILED: proposal not bound to a task card"; exit 1; }
grep -q 'class="launch-client"' "$HTML" || { echo "FAILED: missing launch client selector"; exit 1; }
echo "OK: предложение привязано к карточке, выбор клиента доступен"

brain-dashboard serve --port 19992 &
srv_pid=$!
trap 'kill $srv_pid 2>/dev/null || true' EXIT
sleep 1

# (b) Client override honored (dry-run).
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:19992/api/queue-proposals/qp-test-cli/launch?dry_run=1&client=gemini" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is True, f'override launch should succeed: {d}'
assert d.get('client') == 'gemini', f'expected gemini, got: {d}'
print('OK: client override honored')
" || { echo "FAILED: client override"; exit 1; }

# (c) Invalid client override rejected.
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:19992/api/queue-proposals/qp-test-cli/launch?dry_run=1&client=badcli" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is False, f'bad client should fail: {d}'
assert 'client' in d.get('error','').lower(), f'expected client error: {d}'
print('OK: invalid client rejected')
" || { echo "FAILED: bad client not rejected"; exit 1; }

# (d) No override -> proposal default client.
curl -s --noproxy '*' -H "X-Brain-Confirm: 1" -X POST "http://127.0.0.1:19992/api/queue-proposals/qp-test-cli/launch?dry_run=1" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok') is True, f'default launch should succeed: {d}'
assert d.get('client') == 'codex', f'expected default codex, got: {d}'
print('OK: default client used when no override')
" || { echo "FAILED: default client"; exit 1; }

echo ">>> queue client-select checks passed"
