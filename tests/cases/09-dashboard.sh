#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-dashboard export and status contract"
brain-dashboard export > /dev/null
[ -f "$BRAIN_PATH/wiki/_views/brain-dashboard.html" ] || { echo "FAILED: brain-dashboard.html not created"; exit 1; }
# Редизайн 73f18f2 слил пять пересекающихся секций в единый #task-operations.
grep -q 'id="task-operations"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing task operations section"; exit 1; }
grep -q 'id="locks"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing locks section"; exit 1; }
grep -q 'id="council"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing council section"; exit 1; }
grep -q 'id="index"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing index section"; exit 1; }
grep -q 'id="release-gates"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing release-gates section"; exit 1; }
grep -q 'id="obsidian-views"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing obsidian-views section"; exit 1; }
grep -q 'id="providers"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing providers section"; exit 1; }
grep -q 'id="token-metrics"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing token-metrics section"; exit 1; }
grep -q 'id="handoff-limits"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing handoff-limits section"; exit 1; }
grep -q 'task-filters' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing task filters"; exit 1; }
# Фильтр стал повторяемым на каждой вкладке, поэтому он класс, а не id:
# единственный id на страницу редизайн бы просто продублировал.
grep -q 'class="task-filter-text"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing text filter"; exit 1; }
grep -q 'class="task-filter-priority"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing priority filter"; exit 1; }
grep -q 'class="task-filter-role"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing role filter"; exit 1; }
grep -q 'class="task-filter-mode"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing mode filter"; exit 1; }
# Фильтр по провайдеру редизайн заменил фильтром по заказчику: провайдер —
# свойство запуска, а не задачи, и группировка по нему осталась в статистике.
grep -q 'class="task-filter-client"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing client filter"; exit 1; }
grep -q 'id="task-group-role"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing active role grouping"; exit 1; }
grep -q 'id="task-group-provider"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing active provider grouping"; exit 1; }
grep -q 'id="done-group-role"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing done role grouping"; exit 1; }
grep -q 'id="done-group-provider"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing done provider grouping"; exit 1; }
# Кнопка «Завершить» рисуется только у задач в работе, поэтому её наличие
# зависит от состояния очереди фабрики, а не от вёрстки. Проверка живёт в
# юнит-тесте рендера (test_brain_dashboard_render), где состояние задаётся.
grep -q 'id="launch-panel"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing launch panel"; exit 1; }
grep -q 'id="launch-client"' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing launch client selector"; exit 1; }
grep -q '/api/launch' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing launch API wiring"; exit 1; }
grep -q 'generated-at' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing generated-at timestamp"; exit 1; }
# Status contract: verify dashboard data matches brain-status --json backend
_dash_active=$(brain-status --json | python3 -c "import json,sys; print(json.load(sys.stdin)['tasks']['summary']['active_count'])")
_dash_locks=$(brain-status --json | python3 -c "import json,sys; print(json.load(sys.stdin)['locks']['count'])")
_dash_council=$(brain-status --json | python3 -c "import json,sys; print(json.load(sys.stdin)['council']['count'])")
_dash_index_health=$(brain-status --json | python3 -c "import json,sys; print(json.load(sys.stdin)['index']['health'])")
# preferred равен null, когда ни один кандидат роли не доступен. Прямое
# обращение по ключу давало TypeError и трейсбек вместо диагноза — читать его
# в логе CI бесполезно. Достаём мягко и говорим, чего именно не хватило.
_dash_provider_role=$(brain-status --json | python3 -c "import json,sys; roles=json.load(sys.stdin)['providers']['roles']; print(((roles.get('developer') or {}).get('preferred') or {}).get('provider', ''))")
[ -n "$_dash_provider_role" ] || {
  echo "FAILED: у роли developer нет доступного провайдера — статус не с чем сверять"
  brain-provider status || true
  exit 1
}
grep -q "sse-tasks-active.*>${_dash_active}<\|>${_dash_active}</strong>" "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard active_count ${_dash_active} not found (status contract)"; exit 1; }
grep -q "sse-locks-count.*>${_dash_locks}<\|Total: ${_dash_locks}" "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard lock count ${_dash_locks} not found (status contract)"; exit 1; }
grep -q "sse-council-count.*>${_dash_council}<\|Active sessions: ${_dash_council}" "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard council count ${_dash_council} not found (status contract)"; exit 1; }
grep -q "release-active-count.*>${_dash_active}<" "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: release active_count ${_dash_active} not found (status contract)"; exit 1; }
grep -q "release-index-health.*>${_dash_index_health}<" "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: release index health ${_dash_index_health} not found (status contract)"; exit 1; }
grep -q "${_dash_provider_role}/" "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: provider preferred role ${_dash_provider_role} not found (status contract)"; exit 1; }
# Obsidian views: rebuild with --with-obsidian and verify links in dashboard
brain-index rebuild --with-obsidian > /dev/null
brain-dashboard export > /dev/null
grep -q 'brain-pages.base' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing brain-pages.base link"; exit 1; }
grep -q 'brain-tasks.base' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing brain-tasks.base link"; exit 1; }
grep -q 'link-graph.canvas' "$BRAIN_PATH/wiki/_views/brain-dashboard.html" || { echo "FAILED: dashboard missing link-graph.canvas link"; exit 1; }

echo ">>> Verifying dashboard live_refresh and /api/tasks payload"
python3 - "$PROJECT_ROOT/runtime/bin/brain-dashboard" "$BRAIN_PATH" <<'PYEOF'
import sys, importlib.util, importlib.machinery
from pathlib import Path

loader = importlib.machinery.SourceFileLoader("brain_dashboard", sys.argv[1])
spec = importlib.util.spec_from_loader("brain_dashboard", loader)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

brain = Path(sys.argv[2])

status = mod.collect_status(brain)
ts = "2026-05-03T00:00:00Z"

# build_html with live_refresh=True should include EventSource SSE script
html_live = mod.build_html(status, brain, ts, live_refresh=True)
assert 'EventSource' in html_live, "live_refresh=True missing EventSource SSE script"
assert '/events' in html_live, "live_refresh=True missing /events SSE endpoint reference"
assert 'http-equiv="refresh"' not in html_live, "live_refresh=True must not use meta refresh"
assert 'history.replaceState' in html_live, "query token should be removed from visible URL"
assert 'brainDashboardToken' in html_live, "query token should be persisted locally for API calls"
# Редизайн 73f18f2 сделал фильтр локальным для каждой вкладки: вместо одной
# глобальной applyTaskFilters — обработчик apply() внутри каждой панели.
assert 'task-filter-text' in html_live, "missing client-side task filter"
assert 'data-filter-row=task' in html_live, "missing filterable task rows"
assert 'data-filter-row' in html_live, "missing task row filter attributes"
assert 'data-role=' in html_live, "missing role data attributes"
assert 'data-provider=' in html_live, "missing provider data attributes"
# Блок «Группы задач» редизайн перенёс в секцию статистики (#task-stats).
assert 'id="task-stats"' in html_live, "missing task statistics section"
assert 'active by role' in html_live, "missing role grouping in statistics"
assert 'История (выполнено)' in html_live, "missing done history grouping UI"

# build_html with live_refresh=False (default) must NOT include SSE script
html_export = mod.build_html(status, brain, ts)
assert 'EventSource' not in html_export, "live_refresh=False should not have SSE script"

# /api/tasks payload structure
payload = {
    "tasks": status.get("tasks", {}).get("active", []),
    "summary": status.get("tasks", {}).get("summary", {}),
}
assert isinstance(payload["tasks"], list), "tasks must be list"
assert isinstance(payload["summary"], dict), "summary must be dict"
assert "providers" in status, "status missing providers"
provider_roles = status["providers"]["roles"]
# Проверяем контракт, а не конкретного провайдера: политика живёт в
# config/routing.json и меняется решением оператора, а кейс не должен падать
# при каждой такой правке. Важно, что у роли есть выбранный кандидат и он
# совпадает с первым здоровым по конфигурации.
# Разбор конфигурации берём из библиотеки: она понимает и профили, и
# устаревшую форму со списком кандидатов прямо в роли — а фабрику до нас
# успевают переписать другие кейсы.
import brain_provider as _bp
_matrix = _bp.load_provider_matrix(brain)
for _role in ("architect", "developer"):
    _pref = provider_roles[_role]["preferred"]
    assert _pref, f"{_role}: нет выбранного кандидата: {provider_roles[_role]}"
    _cands, _ = _bp.role_candidates(_matrix, _role)
    _allowed = {c["provider"] for c in _cands}
    assert _pref["provider"] in _allowed, (_role, _pref, _allowed)

# Cached health should demote unavailable candidates without live provider probes.
health_path = brain / ".provider-health.json"
import datetime as dt
now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
# Помечаем нездоровым того кандидата, который сейчас выбран, — какой именно,
# зависит от конфигурации фабрики, а проверяем мы не её, а то, что кэш
# здоровья понижает кандидата без живых проб.
_demoted = provider_roles["developer"]["preferred"]["key"]
import json as _json
health_path.write_text(_json.dumps({
    "updated": now_iso,
    "items": {_demoted: {"status": "unavailable", "reason": "smoke fixture", "checked_at": now_iso}},
}, ensure_ascii=False))
status_with_health = mod.collect_status(brain)
dev = status_with_health["providers"]["roles"]["developer"]
assert _demoted in [u["key"] for u in dev["unavailable"]], (dev, _demoted)
assert not dev["preferred"] or dev["preferred"]["key"] != _demoted, dev
html_provider = mod.build_html(status_with_health, brain, ts)
assert "Provider Matrix" in html_provider, "missing provider matrix section"
assert _demoted in html_provider, "missing demoted provider badge"

# Learning review queue should show lessons without making pending lessons injectable.
lesson_dir = brain / "learning" / "lessons" / "pending"
lesson_dir.mkdir(parents=True, exist_ok=True)
(lesson_dir / "les-20260506-dashboard.md").write_text("""---
id: les-20260506-dashboard
incident_id: inc-20260506-dashboard
status: pending
severity: medium
roles: [developer, reviewer]
tags: [dashboard]
created: 2026-05-06
updated: 2026-05-06
confidence: low
rule: Pending low-signal rule must not be injected.
---

## Rule
Pending low-signal rule must not be injected.
""")
status_with_learning = mod.collect_status(brain)
lesson = next(l for l in status_with_learning["learning"]["recent_lessons"] if l["id"] == "les-20260506-dashboard")
assert lesson["injectable"] is False, lesson
assert lesson["review_required"] is True, lesson
assert lesson["context_tokens_est"] > 0, lesson
html_learning = mod.build_html(status_with_learning, brain, ts)
assert "Lesson Review Queue" in html_learning, "missing learning review queue"
assert "les-20260506-dashboard" in html_learning, "missing lesson row"
assert "pending injected=False" in html_learning, "missing injection policy"

# Token economy metrics should aggregate compacted command records and render raw artifacts.
metrics_dir = brain / ".brain"
metrics_dir.mkdir(parents=True, exist_ok=True)
(metrics_dir / "token-metrics.jsonl").write_text(
    '{"ts":"2026-05-06T00:00:00Z","kind":"rg","provider":"codex","role":"developer","session":"smoke","raw_tokens_est":100,"compact_tokens_est":25,"raw_bytes":400,"compact_bytes":100,"savings_percent":75,"raw_artifact":"/tmp/raw.log"}\n'
)
status_with_tokens = mod.collect_status(brain)
tokens = status_with_tokens["tokens"]
assert tokens["aggregate"]["commands"] == 1, tokens
assert tokens["aggregate"]["savings_percent"] == 75, tokens
html_tokens = mod.build_html(status_with_tokens, brain, ts)
assert "Token Economy" in html_tokens, "missing token economy section"
assert 'id="token-commands"' in html_tokens, "missing live token command counter"
assert 'id="token-raw-tokens"' in html_tokens, "missing live raw token counter"
assert 'id="token-compact-tokens"' in html_tokens, "missing live compact token counter"
assert 'id="token-savings"' in html_tokens, "missing live token savings counter"
assert 'id="token-status"' in html_tokens, "missing token status indicator"
assert "/tmp/raw.log" in html_tokens, "missing raw artifact link text"
assert "smoke" in html_tokens, "missing session"

# Contract path from token-economy docs should also be accepted.
(metrics_dir / "metrics").mkdir(parents=True, exist_ok=True)
(metrics_dir / "token-metrics.jsonl").unlink()
(metrics_dir / "metrics" / "compact.jsonl").write_text(
    '{"ts":"2026-05-06T00:01:00Z","kind":"test","provider":"claude","role":"reviewer","session":"contract-path","raw_tokens_est":80,"compact_tokens_est":20,"raw_bytes":320,"compact_bytes":80,"savings_percent":75,"raw_artifact":"/tmp/contract.log"}\n'
)
status_contract_tokens = mod.collect_status(brain)
contract_tokens = status_contract_tokens["tokens"]
assert contract_tokens["aggregate"]["commands"] == 1, contract_tokens
assert contract_tokens["recent"][0]["session"] == "contract-path", contract_tokens
html_contract_tokens = mod.build_html(status_contract_tokens, brain, ts)
assert "/tmp/contract.log" in html_contract_tokens, "missing contract-path raw artifact"

# Handoff/limits panel should summarize continuation state without rendering raw excerpts.
handoff_dir = brain / "handoff"
handoff_dir.mkdir(parents=True, exist_ok=True)
(handoff_dir / "ORCHESTRATOR_HANDOFF.md").write_text("""# Brain Orchestrator Handoff

generated: 2026-05-06T00:00:00Z
reason: limit-exhausted
from_agent: gemini-3-flash-smoke
to_role: developer
task: t-2026-05-06-current
next_task: t-2026-05-06-next
brain: /tmp/brain

## Next Commands

```bash
brain-status
brain-task take t-2026-05-06-next --as next-agent
brain-run --role developer --task t-2026-05-06-next --agent-id next-agent | claude
```

## Trigger Output Excerpt

```text
SECRET_TOKEN_SHOULD_NOT_RENDER
""" + ("x" * 1200) + """
```
""")
status_with_handoff = mod.collect_status(brain)
handoff = status_with_handoff["handoff"]
assert handoff["exists"] is True, handoff
assert handoff["reason"] == "limit-exhausted", handoff
assert handoff["task"] == "t-2026-05-06-current", handoff
assert handoff["next_task"] == "t-2026-05-06-next", handoff
assert any("brain-task take" in cmd for cmd in handoff["commands"]), handoff
html_handoff = mod.build_html(status_with_handoff, brain, ts)
assert "Handoff & Limits" in html_handoff, "missing handoff panel"
assert "limit-exhausted" in html_handoff, "missing handoff reason"
assert "t-2026-05-06-next" in html_handoff, "missing next task"
assert "brain-task take t-2026-05-06-next" in html_handoff, "missing command preview"
assert "SECRET_TOKEN_SHOULD_NOT_RENDER" not in html_handoff, "raw handoff excerpt leaked"
assert ("x" * 200) not in html_handoff, "long raw excerpt leaked"

# Council workspace read model should distinguish valid/invalid/missing opinions.
task_id = "t-2026-05-06-council-ui-fixture"
active_path = brain / "tasks" / "active.md"
active_path.write_text(active_path.read_text() + f"""

- [ ] [P1] {task_id} — Council UI fixture
      role: architect   mode: council   council: [architect, reviewer, researcher]
      acceptance: fixture
""")
cdir = brain / "council" / task_id
cdir.mkdir(parents=True, exist_ok=True)
(cdir / "architect.md").write_text("""---
task: t-2026-05-06-council-ui-fixture
role: architect
agent: fixture-agent
model: fixture-model
written: 2026-05-06T00:00:00Z
---

## Position
valid

## Reasoning
valid

## Risks / Open questions
none

## Recommendation
valid
""")
(cdir / "reviewer.md").write_text("""---
task: t-2026-05-06-council-ui-fixture
role: reviewer
agent: TODO
model: TODO
written: TODO
---

## Position

## Reasoning

## Risks / Open questions

## Recommendation
""")
status_with_council = mod.collect_status(brain)
fixture = next(c for c in status_with_council["council"]["items"] if c["task_id"] == task_id)
states = {op["role"]: op["status"] for op in fixture["opinions"]}
assert states == {"architect": "valid", "reviewer": "invalid", "researcher": "missing"}, states
assert fixture["synthesis"]["status"] == "not_ready", fixture["synthesis"]
html_council = mod.build_html(status_with_council, brain, ts)
assert "architect: valid" in html_council, "missing valid opinion badge"
assert "reviewer: invalid" in html_council, "missing invalid opinion badge"
assert "researcher: missing" in html_council, "missing missing opinion badge"
print("dashboard live_refresh and /api/tasks payload OK")
PYEOF

echo ">>> Verifying brain-dashboard /events SSE endpoint"
python3 - <<'PYEOF'
import sys, json, time, threading, socket, os
from pathlib import Path
import importlib.machinery, importlib.util
# Скрипт выполняется как heredoc через "python3 -", поэтому __file__ == "<stdin>"
# и Path(__file__).parent не значит "рядом с этим кейсом" — это cwd вызывающего.
# PROJECT_ROOT раннер экспортирует явно (tests/run.sh), на него и опираемся.
src = Path(os.environ["PROJECT_ROOT"]) / "runtime/bin/brain-dashboard"
loader = importlib.machinery.SourceFileLoader("brain_dashboard", str(src))
spec = importlib.util.spec_from_loader("brain_dashboard", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

brain = Path(os.environ.get("BRAIN_PATH", str(Path.home() / "brain")))

# Pick a free port
sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()

import argparse
args = argparse.Namespace(brain=str(brain), port=port)

# Start server in background thread (daemon so it dies with test)
t = threading.Thread(target=mod.cmd_serve, args=(args,), daemon=True)
t.start()

# Ждём готовности сокета опросом, а не фиксированной паузой. Прежний
# time.sleep(0.5) — предположение о скорости раннера: на CI поток не успевал
# забиндиться, и кейс падал с ConnectionRefusedError на здоровом коммите
# (t-2026-08-17-ci-flakes-block-the-recheck). Проверяемое свойство — что
# /events отдаёт event-stream, а не что сервер поднимается за полсекунды.
s = None
deadline = time.time() + 15
while time.time() < deadline:
    candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    candidate.settimeout(8)
    try:
        candidate.connect(("127.0.0.1", port))
    except (ConnectionRefusedError, socket.timeout, OSError):
        candidate.close()
        time.sleep(0.05)
        continue
    s = candidate
    break
assert s is not None, f"dashboard SSE server did not start listening on port {port} within 15s"

# Use raw socket to talk HTTP/1.0 — avoids urllib's redirect/error handling on SSE
s.sendall(b"GET /events HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")

# Read response headers + first data line
raw = b""
deadline = time.time() + 8
while time.time() < deadline:
    try:
        chunk = s.recv(4096)
        if not chunk:
            break
        raw += chunk
        if b"data:" in raw:
            break
    except socket.timeout:
        break
s.close()

response = raw.decode("utf-8", errors="replace")
assert "HTTP/1.0 200" in response or "HTTP/1.1 200" in response, \
    f"Expected 200 from /events, got: {response[:200]}"
assert "text/event-stream" in response, \
    f"Expected text/event-stream, got: {response[:300]}"
data_line = next((l for l in response.splitlines() if l.startswith("data:")), None)
assert data_line, f"No SSE data: line found in /events response: {response[:400]}"
event_data = data_line[5:].strip()
parsed = json.loads(event_data)
assert "ts" in parsed, f"SSE event missing 'ts': {parsed}"
assert "tasks" in parsed, f"SSE event missing 'tasks': {parsed}"
assert "locks" in parsed, f"SSE event missing 'locks': {parsed}"
assert "council" in parsed, f"SSE event missing 'council': {parsed}"
assert "tokens" in parsed, f"SSE event missing 'tokens': {parsed}"
assert "active_count" in parsed["tasks"], f"SSE tasks missing active_count: {parsed}"
assert "aggregate" in parsed["tokens"], f"SSE tokens missing aggregate: {parsed}"
print("/events SSE endpoint OK")
PYEOF
