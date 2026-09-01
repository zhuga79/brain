# Brain Operations Runbook

Диагностика и восстановление при типичных инцидентах.
**Drills verified**: 2026-05-03 on Linux (BRAIN_PATH=/home/user/brain).

---

## 1. Lock Corruption / Stale Lock

**Симптомы:** `brain-task take` возвращает `locked by: …` даже если агент упал.
Или `brain-lock acquire` виснет / возвращает неверный owner.

**Диагностика:**
```bash
brain-status                        # покажет lock count и stale count
brain-status --json | python3 -c "import json,sys; [print(l) for l in json.load(sys.stdin)['locks']['items']]"
ls -la $BRAIN_PATH/.locks/          # посмотреть файлы локов напрямую
cat $BRAIN_PATH/.locks/<task-id>/owner  # прочитать owner и timestamp
```

**Verified output (stale lock present):**
```
Locks: 2 stale=1
```
```
cleaned 1 stale locks
```

**Verified output (clean state):**
```
Locks: 1 stale=0
```

**Восстановление:**
```bash
# Принудительно освободить конкретный лок
brain-lock release <task-id> --as <agent-id> --force

# Очистить все stale локи (TTL истёк)
brain-lock cleanup

# Ручное удаление (крайний случай)
rm -rf $BRAIN_PATH/.locks/<task-id>

# Верификация после очистки
brain-status  # должно показать stale count = 0
```

**Known failure patterns:**
- `brain-lock acquire` prints `claude-sonnet-4-6-b8c3|1777833311|600` and exits 1 → lock already held; use `brain-task take` which handles re-entrancy
- Owner file format: `<agent>|<epoch>|<ttl>` — missing `|` separators = corrupted lock file → delete manually

**Предотвращение:**
- Всегда вызывать `brain-task complete` или `brain-lock release` при завершении
- Использовать `--ttl 3600` (default, 1 ч) — локи автоочищаются после часа без refresh
- Для многочасовых задач: `brain-lock refresh <id> --as <agent>` до истечения TTL

---

## 2. Stale Index

**Симптомы:** `brain-status` выдаёт `health=stale` или `brain-search` возвращает устаревшие результаты.
`brain-lint` сообщает о битых ссылках на страницы, которые существуют.

**Диагностика:**
```bash
brain-status                        # покажет health=stale и stale_files
brain-status --json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['index'])"
brain-lint                          # покажет orphan/broken-link проблемы
```

**Verified output (stale index):**
```
Index: present health=stale [WARN: run brain-index rebuild]
```

**Verified output (after rebuild):**
```
Index: present health=ok
```
```
OK: rebuilt index pages=9 raw=1 links=18 search_docs=13
```

**Восстановление:**
```bash
# Пересборка индекса
brain-index rebuild

# С генерацией Obsidian views
brain-index rebuild --with-obsidian

# Проверка после rebuild
brain-status                        # должно показать health=ok
brain-lint                          # должно пройти без ERROR
brain-lint --sync-report            # проверить Obsidian views
```

**Known failure patterns:**
- `brain-status` shows `health=None` → installed `brain-status` is pre-Phase2; reinstall: `install -m 755 $PROJECT_DIR/runtime/bin/brain-status ~/.local/bin/brain-status`
- `.brain/index/manifest.json` absent → index never built; run `brain-index rebuild`
- `brain-lint` shows `orphan page has no inbound wikilinks` after adding new page → normal until another page links to it

**Когда возникает:**
- После добавления/редактирования wiki/*.md без rebuild
- После `brain-ingest` нового источника
- После ручного создания/переименования страниц

---

## 3. Council Deadlock / Incomplete Council

**Симптомы:** `brain-council synthesize` возвращает "pending opinions" и блокируется.
Одна или несколько ролей застряли на `written: TODO`.

**Диагностика:**
```bash
brain-council status <task-id>      # покажет, какие роли не завершены
brain-council check <task-id>       # machine-checkable guardrails
ls $BRAIN_PATH/council/<task-id>/   # посмотреть файлы напрямую
grep "^written:" $BRAIN_PATH/council/<task-id>/*.md  # проверить timestamps
```

**Восстановление — вариант 1: дождаться роль**
```bash
# Запустить застрявшую роль заново
brain-run --role <role> --task <task-id> | <cli-agent>
# После завершения:
brain-council check <task-id>       # убедиться что OK
brain-council synthesize <task-id>  # создать skeleton
brain-run --role arbiter --task <task-id> --council | <cli-agent>
```

**Восстановление — вариант 2: принудительный синтез**
```bash
# Синтез несмотря на pending роли (solo council или partial)
brain-council synthesize <task-id> --force
brain-run --role arbiter --task <task-id> --council | <cli-agent>
```

**Восстановление — вариант 3: ручное заполнение**
```bash
# Открыть файл роли и заполнить вручную
editor $BRAIN_PATH/council/<task-id>/<role>.md
# Исправить: agent: TODO → agent: manual-recovery
# Исправить: written: TODO → written: <ISO timestamp>
# Заполнить ## Position и ## Recommendation
brain-council check <task-id>       # верификация
```

**Verified output (council check OK with solo WARN):**
```
WARN: solo council — all roles written by the same agent: claude-sonnet-4-6-b8c3
---
council check: t-my-task
  roles: 3  errors: 0  warnings: 1
  status: OK
```

**Verified output (council check FAIL):**
```
ERROR: architect: agent field is TODO or missing
ERROR: architect: ## Position section is empty
---
council check: t-my-task
  roles: 1  errors: 2  warnings: 0
  status: FAIL
```

**Known failure patterns:**
- `brain-council synthesize` exits 1 with "pending opinions" → use `--force` for partial synthesis
- `brain-council check` with no council directory → `ERROR: no council directory for <id>`; run `brain-council start <id>` first

**Solo council (один агент все роли):**
- Является допустимым паттерном (см. [[council-guardrails]])
- `check` выдаёт WARN, не FAIL

---

## 4. MCP Transport Incident

**Симптомы:** MCP-клиент не может подключиться к Brain server.
`brain-mcp` виснет или отваливается сразу.

### 4a. stdio транспорт (Claude Desktop / MCP CLI)

**Диагностика:**
```bash
# Проверить что server.py запускается
python3 $HOME/.local/share/brain/mcp/server.py --help 2>&1 | head -5

# Тест вручную через stdio
echo '{"jsonrpc":"2.0","method":"tools/list","id":1}' | \
  python3 $HOME/.local/share/brain/mcp/server.py 2>/tmp/mcp-stderr.log
cat /tmp/mcp-stderr.log

# Проверить зависимости
python3 -c "import fastmcp; print('fastmcp OK')"
```

**Восстановление:**
```bash
# Переустановить зависимости
pip install --upgrade fastmcp

# Переустановить server.py
install -m 644 $PROJECT_DIR/runtime/mcp/server.py \
  $HOME/.local/share/brain/mcp/server.py

# Проверить конфиг Claude Desktop
cat $HOME/.config/Claude/claude_desktop_config.json
# Убедиться что путь к python3 и server.py верный
```

### 4b. HTTP/SSE транспорт

**Диагностика:**
```bash
# Запустить server с --http и проверить порт
python3 $HOME/.local/share/brain/mcp/server.py --http &
# Verified startup output:
# Brain MCP server starting (SSE/HTTP transport)
#   endpoint : http://127.0.0.1:8766/sse
#   brain    : /home/user/brain
#   tools    : N
# Проверить занятость порта
lsof -i :8766 2>/dev/null || ss -tlnp | grep 8766
```

**Known failure patterns:**
- `ERROR: --port 0 is out of range (must be 1–65535)` → invalid port, use a valid port (1024–65535 recommended)
- `ERROR: cannot bind to 127.0.0.1:8766 — [Errno 98] Address already in use` → port occupied; kill old process or change port
- `ModuleNotFoundError: No module named 'fastmcp'` → install fastmcp: `pip install fastmcp`

**Восстановление:**
```bash
# Убить старый процесс если занимает порт
kill $(lsof -ti :8766) 2>/dev/null || true
# Перезапустить
python3 $HOME/.local/share/brain/mcp/server.py --http

# Если fastmcp не поддерживает --http (старая версия):
pip install --upgrade "fastmcp>=2.0"
```

### 4c. Dashboard serve (brain-dashboard serve)

```bash
# Проверить занятость порта 8765
lsof -i :8765 2>/dev/null
# Перезапустить
kill $(lsof -ti :8765) 2>/dev/null || true
brain-dashboard serve
# Проверить SSE
curl -N --max-time 6 http://127.0.0.1:8765/events | head -3
```

---

## 5. Общая диагностика Brain

```bash
# Полная картина состояния
brain-status

# Все активные задачи
brain-status --json | python3 -c "
import json,sys
d = json.load(sys.stdin)
print('Tasks active:', d['tasks']['summary']['active_count'])
print('Locks:', d['locks']['count'], 'stale:', d['locks']['stale_count'])
print('Council:', d['council']['count'])
print('Index health:', d['index'].get('health', 'unknown'))
"

# Все активные локи
brain-lock list

# Последние операции в логе
tail -20 $BRAIN_PATH/wiki/log.md

# Проверить дерево задач
grep -E "^\- \[" $BRAIN_PATH/tasks/active.md
```

---

## 6. Smoke-тест (быстрая верификация после восстановления)

```bash
cd $PROJECT_DIR  # директория репозитория Brain
bash tests/smoke.sh
```

Все тесты должны завершиться `>>> ALL TESTS PASSED`.

---

## 7. Dashboard serve incident

**Симптомы:** `brain-dashboard serve` не стартует или SSE не работает.

**Диагностика:**
```bash
brain-dashboard serve --port 8765 &
curl -N --max-time 6 http://127.0.0.1:8765/events | head -2
# Expected output: data: {"ts": "...", "tasks": {...}, "locks": {...}, ...}
curl -s http://127.0.0.1:8765/api/audit | python3 -c "import json,sys; d=json.load(sys.stdin); print('audit entries:', d['count'])"
```

**Known failure patterns:**
- SSE returns empty stream → browser or curl blocking, check Content-Type: must be `text/event-stream`
- POST actions return `{"ok":false,"error":"missing ?as=<agent-id>"}` → missing `?as=` parameter in URL
- POST action returns 500 with `brain-task take` error → task already taken; check lock status first
- `/api/audit` returns `{"entries":[],"count":0}` on fresh Brain → normal if log.md has no write-action entries yet

---

## 8. Webhook Incidents

**Симптомы:** `brain-task complete` выводит `WARN: webhook delivery failed (...)`.
Или webhook endpoint не получает события.

### 8a. Timeout

**Диагностика:**
```bash
# Проверить env
echo $BRAIN_WEBHOOK_URL
echo $BRAIN_WEBHOOK_TIMEOUT_SEC   # default: 3

# Тест вручную
curl -s --max-time 3 -X POST "$BRAIN_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d '{"event":"test","task_id":"manual","agent_id":"ops"}'
```

**Expected output (success):**
```
HTTP 200 OK  (or 2xx)
```

**Recovery:**
```bash
# Увеличить timeout
export BRAIN_WEBHOOK_TIMEOUT_SEC=10

# Или отключить webhook
unset BRAIN_WEBHOOK_URL

# complete всегда завершается, даже при webhook timeout
brain-task complete <id> --as <agent>   # OK — task completes
```

**Known failure patterns:**
- `WARN: webhook delivery failed (<urlopen error timed out>)` → endpoint медленный; увеличь `BRAIN_WEBHOOK_TIMEOUT_SEC`
- `WARN: webhook delivery failed (HTTP Error 503)` → upstream сервис недоступен; задача всё равно закрыта
- `WARN: webhook delivery failed ([Errno 111] Connection refused)` → endpoint не запущен; проверь `$BRAIN_WEBHOOK_URL`

### 8b. HTTP 429 (Rate Limit)

**Симптомы:** `WARN: webhook delivery failed (HTTP Error 429: Too Many Requests)`

**Recovery:**
```bash
# Проверить rate limit headers
curl -v -X POST "$BRAIN_WEBHOOK_URL" -d '{}' 2>&1 | grep -i "retry-after\|x-ratelimit"

# Временно отключить webhook до сброса лимита
unset BRAIN_WEBHOOK_URL
# ... выполнить задачи ...
export BRAIN_WEBHOOK_URL=<url>
```

### 8c. Invalid Payload / 4xx

**Симптомы:** `WARN: webhook delivery failed (HTTP Error 400/422)`

**Диагностика:**
```bash
# Проверить payload вручную
python3 -c "
import json, datetime
payload = {
    'event': 'task-done',
    'task_id': 'test-id',
    'agent_id': 'ops-manual',
    'state': 'done',
    'timestamp': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    'brain_path': '/home/user/brain'
}
print(json.dumps(payload, indent=2))
"
```

**Payload schema:**
```json
{
  "event":      "task-done",
  "task_id":    "<task-id>",
  "agent_id":   "<agent-id>",
  "state":      "done",
  "timestamp":  "YYYY-MM-DDTHH:MM:SSZ",
  "brain_path": "/path/to/brain"
}
```

**Recovery:** Проверь, что endpoint принимает `Content-Type: application/json` и ожидаемые поля. Payload не меняется — адаптировать нужно endpoint.

### 8d. Проверка доставки

```bash
# Локальный mock-эндпоинт для проверки
python3 -c "
import http.server, json, threading
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        print('Received:', json.loads(body))
        self.send_response(200); self.end_headers()
    def log_message(self, *a): pass
with http.server.HTTPServer(('127.0.0.1', 9999), H) as s:
    print('Mock webhook at http://127.0.0.1:9999')
    s.serve_forever()
" &
export BRAIN_WEBHOOK_URL=http://127.0.0.1:9999
brain-task complete <task-id> --as <agent>
# Expected: Received: {'event': 'task-done', 'task_id': ...}
```

---

---

## Section 9 — Learning Loop Incidents

### 9a. Зашумлённые уроки (Noisy Lessons)

**Признак:** `brain-run` вставляет нерелевантные уроки или уроков слишком много.

**Диагностика:**
```bash
brain-learn list --status active
# Проверить: roles, tags, severity у каждого активного урока
```

**Лечение:**
```bash
# Устаревший или нерелевантный урок — депрекировать
brain-learn deprecate les-<id> --as <agent-id>
```

**Предотвращение:** При `brain-learn capture` всегда указывай `--role` и `--tags`.

---

### 9b. Плохая активация (Bad Activation)

**Признак:** Активный урок содержит неверное или вредное правило.

**Немедленные действия:**
1. `brain-learn deprecate les-<id> --as <agent-id>`
2. `brain-learn show les-<id>` — проверить scope влияния
3. Вручную проверить задачи, выполненные с этим уроком

**Для high-severity уроков:**
```bash
# Только arbiter одобряет high-severity
brain-learn approve les-<id> --as arbiter-<suffix>
brain-learn activate les-<id>
```

Если arbiter недоступен — урок остаётся в `approved` и не инжектируется.

---

### 9c. Устаревшие уроки (Stale Lessons)

**Признак:** Активные уроки ссылаются на исправленные проблемы.

**Лечение:**
```bash
brain-learn deprecate les-<id> --as <agent-id>
```

**Профилактика:** После завершения фазы:
```bash
brain-learn phase-capture --phase <phase-id> --baseline-tag v<N>
# Ревьюировать pending; депрекировать устаревшие активные
```

---

### 9d. Arbiter Approval Flow

```bash
# 1. Найти high-severity pending
brain-learn list --pending
# Метка: [HIGH - arbiter required]

# 2. Изучить урок
brain-learn show les-<id>

# 3. Одобрить (от имени arbiter-роли)
brain-learn approve les-<id> --as arbiter-<suffix>

# 4. Активировать
brain-learn activate les-<id>

# 5. Или отклонить
brain-learn reject les-<id> --as arbiter-<suffix>
```

**Важно:** `agent-id` при approve не проверяется программно — это организационный контроль.

---

### 9e. Local-Memory Policy

- `$BRAIN_PATH/learning/` **не хранится в git** по умолчанию.
- Код (`runtime/bin/brain-learn`, `runtime/lib/brain_learning.py`) хранится в git.
- При переустановке Brain — learning-данные не переносятся автоматически. Резервное копирование — на усмотрение пользователя.

---

---

## Section 10 — Policy Denied Incidents

### 10a. Claude Code — bash tool blocked

**Признак:** `Error: tool 'bash' is not allowed` или аналогичное при попытке выполнить brain-команду.

**Лечение:**
```bash
# В интерактивной сессии: одобри bash/write/read при первом запросе
# Или запусти с явным разрешением:
claude --dangerously-skip-permissions -p "$(brain-run --role developer --task <id>)"
```

### 10b. Codex — run_shell_command blocked

**Признак:** Codex отклоняет `run_shell_command` для brain-команд.

**Диагностика:**
```bash
cat ~/.codex/AGENTS.md   # должен указывать на ~/brain/MEMORY.md
# Проверить, что MEMORY.md не запрещает run_shell_command явно
```

**Лечение:** Добавить в ~/.codex/settings.json (или policy config):
```json
{ "allowedTools": ["run_shell_command"] }
```

### 10c. Policy readiness check

```bash
brain-policy check
# Выводит: provider, allowed ops, any blocked Brain commands
# Exit 0 = ready, Exit 1 = blocked ops found
```

При exit 1 — смотри вывод для конкретного блокера. Не начинай работу над задачей до прохождения policy check.

---

---

## Section 11 — Phase 6 Reliability (webhook/learning/failover/metrics)

### 11a. Webhook Dead-Letter Queue

**Признак:** `WARN: webhook delivery failed after N attempts (...); queued in .webhooks/dead-letter.jsonl`

**Диагностика:**
```bash
cat $BRAIN_PATH/.webhooks/dead-letter.jsonl   # смотреть очередь
wc -l $BRAIN_PATH/.webhooks/dead-letter.jsonl # количество застрявших событий
```

**Recovery:**
```bash
# После восстановления webhook endpoint
export BRAIN_WEBHOOK_URL=https://your-endpoint/hook
brain-task webhook-replay
# Expected output: replayed=N remaining=0
```

**Известные ошибки:**
- `remaining=N` после replay → endpoint всё ещё недоступен; повтори позже
- `dead-letter.jsonl is empty` → очередь уже пуста; задачи уже доставлены ранее

---

### 11b. Duplicate Lesson Blocked

**Признак:** `brain-learn activate <id>` выводит `Duplicate lesson detected: les-... already active with the same rule.`

**Диагностика:**
```bash
brain-learn quality-check --id <id>      # покажет дублирующий урок
brain-learn list --status active         # посмотреть активные уроки
```

**Recovery:**
```bash
# Вариант A: deprecated дубликат и активировать новый
brain-learn deprecate <existing-id> --as <agent>
brain-learn activate <new-id> --as <agent>

# Вариант B: отклонить новый урок как дубликат
brain-learn reject <new-id> --as <agent>
```

---

### 11c. Expired Lessons Injected

**Признак:** `brain-run` вставляет урок с истёкшей датой `expires`.

**Диагностика:**
```bash
brain-learn list --status active   # смотреть поле expires у активных
# Уроки с expires в прошлом должны быть filtered автоматически
```

**Recovery:**
```bash
brain-learn prune-expired   # deprecate все просроченные active уроки
# Expected: deprecated (expired): les-..., Pruned N expired lesson(s).
```

---

### 11d. Release Gate Blocked

**Признак:** `brain-release check` выводит `FAIL` по одному из gate'ов.

**Диагностика:**
```bash
brain-release check   # показывает все gate-результаты с деталями блокера
```

**Gate-блокеры и лечение:**

| Gate | Блокер | Действие |
|---|---|---|
| `active=0` | Есть открытые задачи | Закрыть или заблокировать все `- [ ]` задачи |
| `brain-lint` | Orphaned страницы / stale locks | `brain-lint` для деталей; удали / исправь |
| `brain-validate` | Нарушение контракта wiki | `brain-validate` для деталей; исправь ссылки |
| `tests/smoke.sh` | Упавший тест | Запусти `bash tests/smoke.sh` отдельно; исправь регрессию |
| `index health` | Stale index | `brain-index rebuild` |

После устранения всех блокеров:
```bash
brain-release check        # должно: All release gates passed. Ready to tag.
brain-release tag v6       # создаёт тег (с подтверждением)
```

---

### 11e. Failover Drills

Для проверки failover-устойчивости:
```bash
bash tests/e2e-failover.sh   # все 3 drill'а (~8 сек)
```

| Drill | Проверяет |
|---|---|
| 1 — Stale-lock takeover | Лок TTL и автозахват другим агентом |
| 2 — Dead-letter replay | Webhook dead-letter → replay → очистка |
| 3 — Council partial | Синтез из неполных мнений совета |

---

### 11f. Metrics Unavailable

**Признак:** `GET /api/metrics` возвращает 503 или пустой ответ.

**Диагностика:**
```bash
# Проверить, что сервер запущен
brain-dashboard serve --port 8765 &
curl --noproxy '*' http://127.0.0.1:8765/api/metrics
```

**Известные причины:**
- `collect_metrics` падает при отсутствии `tasks/active.md` — убедись что brain инициализирован (`setup-brain-v2.sh`)
- Системный proxy перехватывает localhost — используй `--noproxy '*'` в curl или `ProxyHandler({})` в Python

---

## 12. Orchestrator Handoff On Limits

**Признак:** текущий CLI-оркестратор получил `HTTP 429`, `Too Many Requests`,
`RESOURCE_EXHAUSTED`, `quota`, `rate limit`, `context length` или
`token limit`.

**Ручная передача:**
```bash
brain-handoff create --reason limit-exhausted --from <agent-id> --to-role developer --task <task-id>
brain-handoff show
```

**Автоматическая обёртка вокруг CLI:**
```bash
brain-handoff run --task <task-id> --agent <agent-id> --to-role developer -- \
  <cli-command> <args>
```

Если команда вернёт ненулевой exit code и в stdout/stderr будет limit-pattern,
`brain-handoff` запишет `$BRAIN_PATH/handoff/ORCHESTRATOR_HANDOFF.md`, добавит
`orchestrator-handoff` в `wiki/log.md` и вернёт исходный exit code команды.

Для `brain-launch`:
```bash
brain-launch <task-id> --handoff-on-limit
brain-launch <task-id> --dry-run --handoff-on-limit
```

Для реального auto-fallback на другой CLI:

```bash
brain-orchestrator run \
  --task <task-id> \
  --agent <current-agent-id> \
  --to-role developer \
  --fallback "claude -p /tmp/brain-next-prompt.md" \
  -- <primary-cli-command> <args>
```

`brain-orchestrator` использует `brain-handoff run` для primary. Если primary
падает с limit-pattern (`429`, `RESOURCE_EXHAUSTED`, `quota`, `rate limit`,
`context length`, `token limit`), он пишет handoff artifact и запускает fallback.
Обычные non-limit ошибки fallback не запускают.

**Recovery:**
```bash
brain-handoff show
brain-status
brain-task list
# Следующий CLI берёт next task только через lock protocol:
brain-task take <next-id> --as <new-agent-id>
```

**Важно:** handoff-файл локальный и может содержать фрагмент stderr/stdout
упавшей CLI-команды. Не вставляй туда секреты и не коммить `~/brain/handoff/`
как публичный артефакт.

---

## 13. Dashboard Read/Write Security

`brain-dashboard serve` должен слушать loopback (`127.0.0.1`). Task write
actions требуют header:

```http
X-Brain-Confirm: 1
```

Если задан `BRAIN_DASHBOARD_AUTH_TOKEN`, write actions дополнительно требуют:

```http
X-Brain-Token: <token>
```

Read endpoints (`/`, `/events`, `/api/*`) при заданном
`BRAIN_DASHBOARD_AUTH_TOKEN` тоже требуют токен:

```http
X-Brain-Token: <token>
```

или query-token для browser/SSE bootstrap:

```text
http://127.0.0.1:8765/?token=<token>
```

Для скриптов предпочитай header. URL с `?token=` считать чувствительным:
не вставлять в публичные логи, issues, handoff или screenshots.

Non-loopback bind (`--host 0.0.0.0`) без `BRAIN_DASHBOARD_AUTH_TOKEN`
завершается ошибкой. Для remote-доступа предпочитай SSH tunnel или loopback
forwarding.

Dashboard UI ставит его автоматически. Ручная проверка:

```bash
# Должно вернуть ok=false и ошибку про X-Brain-Confirm
curl --noproxy '*' -X POST \
  "http://127.0.0.1:8765/api/tasks/<id>?as=ops&action=take"

# Разрешённый локальный write
curl --noproxy '*' -H "X-Brain-Confirm: 1" -X POST \
  "http://127.0.0.1:8765/api/tasks/<id>?as=ops&action=take"
```

Не публикуй dashboard write API на внешний интерфейс без auth-token слоя.

## 14. Provider Health Cache Refresh

`brain-status`, dashboard, MCP и SSE не делают live provider probes. Обновление
cache только вручную:

```bash
brain-provider status --json
brain-provider refresh --provider gemini --model gemini-3-flash --timeout 30
brain-provider refresh --provider gemini --model gemini-3-flash --timeout 30 --yes
brain-provider mark --provider gemini --model gemini-3-flash --status rate-limited --reason "HTTP 429" --yes
brain-provider clear --provider gemini --model gemini-3-flash --yes
```

`$BRAIN_PATH/.provider-health.json` — generated local state. Не коммить его.

## 15. Handoff JSON

Для передачи состояния другому CLI без Markdown parsing:

```bash
brain-handoff create --reason limit-exhausted --from <agent> --to-role developer --json
brain-handoff show --json
```

`trigger_excerpt` в JSON bounded, но всё равно локальный failure output. Не
логируй и не коммить его как безопасный текст.

## 16. Federation Dry-Run Preflight

Phase 10 federation tooling is read-only. Phase 11 adds controlled local write
commands, but still does not pull, push, merge or run provider CLIs.

```bash
brain-federation support --json
brain-federation preflight --repo <path> --brain "$BRAIN_PATH" --json
brain-federation tasks-check --active proposed-active.md --done proposed-done.md --json
brain-federation plan --repo <path> --brain "$BRAIN_PATH" --out /tmp/plan.json
brain-federation import-tasks --plan /tmp/plan.json --as <agent-id> --json
brain-federation write-wiki-proposals --plan /tmp/plan.json --as <agent-id> --json
```

Exit codes:

- `0`: no `block` findings;
- `1`: one or more `block` findings;
- `2`: bad input/usage.

Blocking examples:

- `.locks/`, `.brain/`, `.provider-health.json`, `.cli-mapping.sh`,
  `handoff/ORCHESTRATOR_HANDOFF.md`, `wiki/_views/`;
- modified/deleted existing `raw/*`;
- changed `wiki/*.md` with `protected: true` or `curation: human`;
- duplicate task ids, imported `[~]`, active/done conflicts.

Review-only examples:

- `wiki/provider-matrix.json` changed;
- provider `command` changed inside the matrix;
- lesson status conflict;
- stale council synthesis.

Phase 11 write gates:

- `import-tasks` is dry-run unless `--yes` is present.
- It refuses stale source fingerprints, any plan `block`, duplicate ids,
  active/done conflicts and non-open task states.
- It writes only `tasks/active.md` and `wiki/log.md`.
- `write-wiki-proposals` is dry-run unless `--yes` is present.
- It writes only `proposals/federation/<timestamp>/` with `manifest.json`,
  proposed markdown, unified diff and captured target metadata.
- It never writes `wiki/` or `raw/`, including unprotected pages.
- Optional local secret scanner uses `BRAIN_SECRET_SCANNER_CMD`; unavailable
  scanners produce warning/fallback only and do not trigger installs.

Typical drill:

```bash
brain-federation preflight --repo . --brain "$BRAIN_PATH" --json
brain-federation tasks-check --active /tmp/proposed-active.md --done /tmp/proposed-done.md
```

If provider matrix changes are reported, review `provider`, `model` and
`command` fields before any later `brain-provider refresh --yes`.

Dashboard token hygiene:

```bash
BRAIN_DASHBOARD_AUTH_TOKEN=<token> brain-dashboard serve
# Browser bootstrap may use /?token=<token>; the page stores it locally and
# removes token from the visible URL via history.replaceState.
```

Prefer `X-Brain-Token` for scripts. Treat copied URLs containing `?token=` as
sensitive local artifacts.

---

*Обновлено: 2026-05-07 (Phase 11 — controlled federation import, proposal artifacts, dashboard token cleanup, optional secret scanner). Связанные страницы: [[decisions-log]], [[cli-cheatsheet]].*
