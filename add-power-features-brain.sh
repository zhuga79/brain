#!/usr/bin/env bash
# add-power-features-brain.sh
# Три фичи поверх brain v2:
#   1. PRD-режим: architect декомпозирует mode:prd-задачу в developer-тикеты с deps
#   2. Tmux-launcher: brain-launch <task-id> поднимает совет в tmux окнах
#   3. Git-автокоммит: brain-task complete коммитит изменения в ~/brain/.git
#
# Идемпотентен.

set -euo pipefail
# ── Phase 7 deprecation notice ────────────────────────────────────────────────
# Direct invocation of this script is deprecated. Prefer:
#   bash setup-brain-v2.sh --module <name>
# Setting BRAIN_MODULE_INVOCATION=1 (done by setup-brain-v2.sh) suppresses this.
if [ -z "${BRAIN_MODULE_INVOCATION:-}" ]; then
  echo "WARN: legacy invocation of $(basename "$0"). Use: setup-brain-v2.sh --module <name>" >&2
fi

BRAIN="${BRAIN_PATH:-$HOME/brain}"

# Отказ работать, если BRAIN — git worktree: у worktree `.git` — файл со
# ссылкой на общий gitdir основного чекаута, и git-автокоммит этого скрипта
# ниже (PART 3) при первом запуске делает `git init`, который для такого
# дерева по умолчанию пишет в ОБЩИЙ .git/config и может испортить основной
# чекаут (сломал core.bare 2026-08-16, см. CONTRIBUTING.md). Тот же guard,
# что и в setup-brain-v2.sh — этот скрипт вызывается и напрямую, в обход
# него (tests/run.sh так и делает).
if [ -f "$BRAIN/.git" ] && grep -q '^gitdir:' "$BRAIN/.git" 2>/dev/null; then
  echo "ОТКАЗ: $BRAIN — git worktree (общий .git/config с основным чекаутом)." >&2
  echo "  Git-автокоммит не поддерживает worktree как рабочее дерево." >&2
  echo "  Используйте обычный git clone/checkout вместо worktree." >&2
  exit 3
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

[ ! -f "$BRAIN/MEMORY.md" ] && { echo "Сначала setup-brain-v2.sh"; exit 1; }

mkdir -p "$BRAIN/prd"

# =============================================================================
# PART 1. PRD-режим
# =============================================================================

# SCHEMA.md ставит setup-brain-v2.sh из runtime/templates/v2. Вторая копия
# здесь разошлась с первой: в одной были depends_on и mode:prd, в другой —
# client и project, и какая доедет до пользователя, решал порядок запуска.

# Шаблон PRD-файла
cat > "$BRAIN/prd/_TEMPLATE.md" <<'EOF'
---
parent: <task-id>
created: <ts>
status: draft
---

# PRD: <Title>

## Goal
<Что должно быть сделано в одном абзаце. Какой результат>

## Why
<Зачем. Какая проблема решается. Какая гипотеза.>

## Scope
### In scope
-
### Out of scope (non-goals)
-

## Constraints
<Технические, временные, бюджетные ограничения>

## Decomposition rationale
<Почему именно такая декомпозиция. Какие альтернативы рассмотрены.>

## Acceptance for parent task
<Когда родительская PRD-задача считается выполненной — обычно после того,
как все сабтаски выполнены и интеграционные acceptance работают>

## Subtasks

> Формат: каждый сабтаск — markdown-чекбокс с метаданными.
> ID автогенерится на основе parent: <parent>-s1, <parent>-s2, ... либо
> можно задать явно после "—".
> depends_on: ссылается на ранее перечисленные id или на другие задачи.

- [ ] [P1] s1 — Название первого сабтаска
      role: developer
      depends_on: []
      acceptance: что считается готовым
      ref: [[wiki/...]]

- [ ] [P1] s2 — Название второго
      role: developer
      depends_on: [s1]
      acceptance: ...

- [ ] [P2] s3 — Документация
      role: researcher
      depends_on: [s2]
      acceptance: ...
EOF

# brain-prd CLI


# =============================================================================
# Обновим brain-task: учитывать depends_on в next, дополнить deps
# =============================================================================

# Устанавливаем brain-task из runtime/bin, чтобы runtime-код ревьюился и тестировался отдельно.

# CLI-инструменты ставит setup-brain-v2.sh обходом runtime/bin — здесь их
# перечислять нельзя: второй список неизбежно отстаёт от первого.

# =============================================================================
# PART 2. tmux-launcher
# =============================================================================

# Запасная конфигурация маршрутизации — на случай запуска этого скрипта в
# обход setup-brain-v2.sh, который ставит её из дерева. Покрывает РОВНО те
# роли, что лежат в $BRAIN/roles: конфигурация с шестью ролями из тридцати
# означает, что двадцать четыре роли уходят в defaults.cli без модели.
if [ ! -f "$BRAIN/config/routing.json" ]; then
mkdir -p "$BRAIN/config"
python3 - "$BRAIN" <<'PYEOF'
import json
import sys
from pathlib import Path

brain = Path(sys.argv[1])
roles = sorted(p.stem for p in (brain / "roles").glob("*.md"))
# Роли, где цена ошибки рассуждения выше цены токенов.
THINKING = {"architect", "arbiter", "reviewer", "security", "researcher", "lawyer",
            "compliance", "tax-advisor", "cfo", "strategist", "product", "pm",
            "negotiator", "designer", "maintainer", "growth-analyst",
            "taste-reviewer", "impeccable-reviewer", "renovation-planner"}
config = {
    "version": 2,
    "schema": "routing/v2",
    "updated": "",
    "note": "Запасная конфигурация. Разведи роли по профилям под свои CLI.",
    "defaults": {"cli": "claude"},
    "providers": {"claude": {"command": "claude", "model_flag": "--model {model}", "enabled": True}},
    "profiles": {
        "thinking": [{"rank": 1, "provider": "claude", "model": "opus", "use_for": "проектирование, критика, синтез"}],
        "doing": [{"rank": 1, "provider": "claude", "model": "sonnet", "use_for": "реализация и рутина"}],
    },
    "roles": {r: {"profile": "thinking" if r in THINKING else "doing"} for r in roles},
}
(brain / "config" / "routing.json").write_text(
    json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"\u2713 config/routing.json: {len(roles)} ролей")
PYEOF
fi


# =============================================================================
# PART 3. Git auto-commit
# =============================================================================

# Init git если ещё нет. `-e`, а не `-d`: в worktree `.git` — файл, а не
# каталог, и старая проверка `-d` этого не видела — считала репозиторий
# отсутствующим и звала `git init` внутрь уже существующего worktree.
if [ ! -e "$BRAIN/.git" ]; then
  if command -v git >/dev/null; then
    (cd "$BRAIN" && git init --quiet && git config user.name "brain" && git config user.email "brain@local")
    echo "✓ git initialized in $BRAIN"
  else
    echo "! git не найден — auto-commit отключён"
  fi
fi

# .gitignore — только если его ещё нет. Безусловная запись затирала
# настоящий .gitignore репозитория: скрипт запускается повторно, и
# каждый запуск отменял все накопленные правила.
if [ ! -f "$BRAIN/.gitignore" ]; then
cat > "$BRAIN/.gitignore" <<'EOF'
# brain .gitignore

# локи (эфемерные)
.locks/

# конфиги CLI-агентов (симлинки наружу)
.agent-configs/

# generated machine indexes
.brain/index/

# редакторские бэкапы
*.bak
*.tmp
*~
.DS_Store
EOF
fi

# Первый коммит если репо пустое
(
  cd "$BRAIN"
  if [ -d ".git" ] && ! git rev-parse HEAD >/dev/null 2>&1; then
    git add -A 2>/dev/null
    git commit -m "init brain" --quiet 2>/dev/null || true
  fi
)

# =============================================================================
# Патч MEMORY.md — упоминания PRD/launch/git
# =============================================================================

python3 - "$BRAIN/MEMORY.md" <<'PY'
import sys, pathlib, re
p = pathlib.Path(sys.argv[1])
txt = p.read_text()

prd_section = """## PRD-mode

Крупные работы — задачи с `mode: prd`. Берёт `architect`. Workflow:

1. `brain-prd init <task-id>` — создаст `~/brain/prd/<id>.md` по шаблону.
2. Архитектор заполняет PRD, особенно секцию `## Subtasks`.
3. `brain-prd commit <id>` — сабтаски попадают в `active.md` с правильными `depends_on`.
4. `brain-task next --role developer` показывает первый available сабтаск
   (с уже выполненными deps).
5. По завершении всех сабтасков — closing родительской PRD-задачи.

`brain-task deps <id>` — показывает граф зависимостей.

## Tmux-launcher

`brain-launch <task-id>` поднимает tmux-сессию с одним окном на роль из
совета задачи. Каждое окно запускает `brain-run --role X | <CLI>`.
Маршрутизация роль→CLI: `~/brain/config/routing.json` (через `brain-provider cli`).

## Git auto-commit

`~/brain/` — git-репозиторий. Каждая операция `brain-task add/take/release/
complete/block` делает коммит в локальный репо. Это даёт:
- историю изменений wiki/задач/советов;
- возможность откатить ошибочное удаление;
- (опционально) push в private remote для синка между машинами.

"""

# вставить перед "## Принципы" если ещё нет
if "## PRD-mode" not in txt:
    if "## Принципы" in txt:
        txt = txt.replace("## Принципы", prd_section + "## Принципы", 1)
    else:
        txt += "\n" + prd_section
    p.write_text(txt)
    print("MEMORY.md updated")
else:
    print("MEMORY.md already has PRD section")
PY

# =============================================================================
# Пример PRD-задачи
# =============================================================================
if ! grep -q "prd-example" "$BRAIN/tasks/active.md"; then
cat >> "$BRAIN/tasks/active.md" <<'EOF'

- [ ] [P2] t-2026-05-01-prd-example — Внедрить новую фичу X
      role: architect   mode: prd
      acceptance: PRD заполнен, сабтаски в active.md, все зависимости выстроены.
EOF
fi

echo
echo "==============================================================="
echo "  Power features добавлены в brain"
echo "==============================================================="
cat <<INFO

1. PRD-режим
   brain-prd init <task-id>      — шаблон prd/<id>.md
   brain-prd commit <task-id>    — залить сабтаски в active.md
   brain-prd status <task-id>    — прогресс
   brain-task next --role developer — учитывает depends_on
   brain-task deps <id>          — граф зависимостей

2. Tmux-launcher
   brain-launch <task-id>           — старт сессии brain-<id>
   brain-launch <task-id> --dry-run — посмотреть что запустилось бы
   ~/brain/config/routing.json — маршрутизация роль → CLI команда

3. Git auto-commit
   ~/brain/ инициализирован как git-репо.
   Каждая операция brain-task делает локальный коммит.
   Опционально: добавь remote и push для синка между машинами:
     cd ~/brain && git remote add origin <your-private-repo>
     cd ~/brain && git push -u origin main

Пример полного цикла:
  brain-prd init t-2026-05-01-prd-example
  # отредактируй ~/brain/prd/t-2026-05-01-prd-example.md
  brain-prd commit t-2026-05-01-prd-example
  brain-task next --role developer
  brain-task take <subtask-id> --as dev-1
  # ... работа ...
  brain-task complete <subtask-id> --as dev-1
  # → автокоммит в git, разблокирует следующий depends_on этого

INFO
