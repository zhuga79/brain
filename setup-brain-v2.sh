#!/usr/bin/env bash
# brain v2 — единая память + роли + блокировки + консилиум
# Совместимо с brain v1 (просто запусти поверх — обновит структуру).
#
# Что нового:
#   • roles/        — persona-файлы для разных агентных ролей
#   • .locks/       — атомарные локи на задачи (TTL, agent-id)
#   • council/      — консилиум: несколько моделей по одной задаче
#   • brain-task    — расширен: take/release/complete/list по ролям
#   • brain-lock    — acquire/release/status/cleanup
#   • brain-council — start/status/synthesize
#   • brain-run     — собирает промпт (память + роль + задача) под CLI

set -euo pipefail

# ── Argument parsing (Phase 7: --module support) ─────────────────────────────
MODULES=""
while [ $# -gt 0 ]; do
  case "$1" in
    --module)
      MODULES="$2"; shift 2 ;;
    --module=*)
      MODULES="${1#--module=}"; shift ;;
    -h|--help)
      cat <<USAGE
Usage: setup-brain-v2.sh [--module <list>]

Options:
  --module pm-finance,design-negotiator,teams,power-features,tax-boundaries,doctrine
                  Comma-separated list of optional modules to install on top
                  of the base setup. Each module wraps a legacy add-*.sh:
                    pm-finance        → add-pm-finance-brain.sh
                    design-negotiator → add-design-negotiator-brain.sh
                    teams             → add-teams-brain.sh
                    power-features    → add-power-features-brain.sh
                    tax-boundaries    → refine-tax-boundaries.sh
                    doctrine          → patch-brain-run-doctrine.sh
  -h, --help      Show this help.
USAGE
      exit 0 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 2 ;;
  esac
done

BRAIN="${BRAIN_PATH:-$HOME/brain}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SYSTEM_ROOT="${BRAIN_SYSTEM_PATH:-$SCRIPT_DIR}"
V2_TEMPLATES="$SCRIPT_DIR/runtime/templates/v2"
TEMPLATE_MEMORY="$V2_TEMPLATES/MEMORY.md"
[ -f "$SCRIPT_DIR/MEMORY.md" ] && TEMPLATE_MEMORY="$SCRIPT_DIR/MEMORY.md"
TEMPLATE_ROLES="$V2_TEMPLATES/roles"
[ -d "$SCRIPT_DIR/roles" ] && TEMPLATE_ROLES="$SCRIPT_DIR/roles"
TEMPLATE_TEAMS="$V2_TEMPLATES/teams"
[ -d "$SCRIPT_DIR/teams" ] && TEMPLATE_TEAMS="$SCRIPT_DIR/teams"
TEMPLATE_DOCTRINE="$V2_TEMPLATES/doctrine"
[ -d "$SCRIPT_DIR/doctrine" ] && TEMPLATE_DOCTRINE="$SCRIPT_DIR/doctrine"
TEMPLATE_WIKI="$V2_TEMPLATES/wiki"
[ -d "$SCRIPT_DIR/wiki" ] && TEMPLATE_WIKI="$SCRIPT_DIR/wiki"
TEMPLATE_RAW="$V2_TEMPLATES/raw"
[ -d "$SCRIPT_DIR/raw" ] && TEMPLATE_RAW="$SCRIPT_DIR/raw"
TEMPLATE_SKILLS="$V2_TEMPLATES/skills"
[ -d "$SCRIPT_DIR/skills" ] && TEMPLATE_SKILLS="$SCRIPT_DIR/skills"
TEMPLATE_ROUTING="$V2_TEMPLATES/config/routing.json"
[ -f "$SCRIPT_DIR/config/routing.json" ] && TEMPLATE_ROUTING="$SCRIPT_DIR/config/routing.json"

same_path() {
  local left="$1"
  local right="$2"
  [ "$(readlink -f "$left" 2>/dev/null || printf '%s' "$left")" = \
    "$(readlink -f "$right" 2>/dev/null || printf '%s' "$right")" ]
}

SPLIT_ROOT=0
if [ -n "${BRAIN_SYSTEM_PATH:-}" ] && ! same_path "$BRAIN" "$SYSTEM_ROOT"; then
  SPLIT_ROOT=1
fi

echo ">>> brain v2 path: $BRAIN"
mkdir -p "$BRAIN"/{raw,wiki,tasks,council,.locks,.agent-configs}
if [ "$SPLIT_ROOT" -eq 0 ]; then
  mkdir -p "$BRAIN"/{roles,teams,doctrine,skills}
fi

# =============================================================================
# Load static templates
# =============================================================================
copy_md_dir() {
  local src="$1"
  local dst="$2"
  local mode="${3:-overwrite}"
  [ -d "$src" ] || return 0
  mkdir -p "$dst"
  local f
  for f in "$src"/*.md; do
    [ -f "$f" ] || continue
    local target="$dst/$(basename "$f")"
    if [ "$mode" = "missing" ] && [ -f "$target" ]; then
      continue
    fi
    if [ -e "$target" ] && [ "$(readlink -f "$f")" = "$(readlink -f "$target")" ]; then
      continue
    fi
    cp "$f" "$target"
  done
}

if [ ! -e "$BRAIN/MEMORY.md" ] || { [ "$SPLIT_ROOT" -eq 0 ] && ! same_path "$TEMPLATE_MEMORY" "$BRAIN/MEMORY.md"; }; then
  cp "$TEMPLATE_MEMORY" "$BRAIN/MEMORY.md"
fi

if [ "$SPLIT_ROOT" -eq 0 ]; then
  copy_md_dir "$TEMPLATE_ROLES" "$BRAIN/roles" overwrite

  # Маршрутизация ставится вместе с ролями и из того же дерева: иначе роли
  # приезжают все тридцать, а маршруты — шесть, и brain-validate краснеет на
  # свежей установке. Существующий файл не трогаем: это политика оператора.
  if [ -f "$TEMPLATE_ROUTING" ] && [ ! -f "$BRAIN/config/routing.json" ]; then
    mkdir -p "$BRAIN/config"
    cp "$TEMPLATE_ROUTING" "$BRAIN/config/routing.json"
  fi
  copy_md_dir "$TEMPLATE_TEAMS" "$BRAIN/teams" overwrite
  copy_md_dir "$TEMPLATE_DOCTRINE" "$BRAIN/doctrine" overwrite
  # Машиночитаемая escalation matrix — yaml, а copy_md_dir копирует только *.md.
  # Без неё brain-validate краснеет на свежей установке (doctrine/ есть, файла нет).
  if [ -f "$TEMPLATE_DOCTRINE/escalation-matrix.yaml" ]; then
    mkdir -p "$BRAIN/doctrine"
    # Тот же файл — не ошибка: BRAIN может указывать на само дерево (симлинк).
    if ! same_path "$TEMPLATE_DOCTRINE/escalation-matrix.yaml" "$BRAIN/doctrine/escalation-matrix.yaml"; then
      cp "$TEMPLATE_DOCTRINE/escalation-matrix.yaml" "$BRAIN/doctrine/escalation-matrix.yaml"
    fi
  fi
  if [ -d "$TEMPLATE_SKILLS" ]; then
    mkdir -p "$BRAIN/skills"
    if ! same_path "$TEMPLATE_SKILLS" "$BRAIN/skills"; then
      cp -R "$TEMPLATE_SKILLS/." "$BRAIN/skills/"
    fi
  fi
fi
copy_md_dir "$TEMPLATE_RAW" "$BRAIN/raw" missing

if [ ! -f "$BRAIN/tasks/SCHEMA.md" ] || ! cmp -s "$V2_TEMPLATES/tasks/SCHEMA.md" "$BRAIN/tasks/SCHEMA.md"; then
  cp "$V2_TEMPLATES/tasks/SCHEMA.md" "$BRAIN/tasks/SCHEMA.md"
fi
[ ! -f "$BRAIN/tasks/active.md" ] && cp "$V2_TEMPLATES/tasks/active.md" "$BRAIN/tasks/active.md"

# tasks/done.md и wiki/index.md и wiki/log.md (если ещё нет)
[ ! -f "$BRAIN/tasks/done.md" ] && cp "$V2_TEMPLATES/tasks/done.md" "$BRAIN/tasks/done.md"
[ ! -f "$BRAIN/wiki/index.md" ] && [ -f "$TEMPLATE_WIKI/index.md" ] && cp "$TEMPLATE_WIKI/index.md" "$BRAIN/wiki/index.md"
[ ! -f "$BRAIN/wiki/log.md" ] && [ -f "$TEMPLATE_WIKI/log.md" ] && cp "$TEMPLATE_WIKI/log.md" "$BRAIN/wiki/log.md"
for wiki_template in "$TEMPLATE_WIKI/"*; do
  [ -f "$wiki_template" ] || continue
  wiki_name="$(basename "$wiki_template")"
  case "$wiki_name" in
    index.md|log.md) continue ;;
  esac
  [ ! -f "$BRAIN/wiki/$wiki_name" ] && cp "$wiki_template" "$BRAIN/wiki/$wiki_name"
done

# =============================================================================
# Симлинки конфиг-файлов
# =============================================================================
ln -sf ../MEMORY.md "$BRAIN/.agent-configs/CLAUDE.md"
ln -sf ../MEMORY.md "$BRAIN/.agent-configs/AGENTS.md"
ln -sf ../MEMORY.md "$BRAIN/.agent-configs/GEMINI.md"
ln -sf ../MEMORY.md "$BRAIN/.agent-configs/.cursorrules"

mkdir -p "$HOME/.claude" "$HOME/.codex" "$HOME/.gemini"
for target in "$HOME/.claude/CLAUDE.md" "$HOME/.codex/AGENTS.md" "$HOME/.gemini/GEMINI.md"; do
  if [ ! -e "$target" ] || [ -L "$target" ]; then
    ln -sf "$BRAIN/MEMORY.md" "$target" 2>/dev/null || true
  else
    echo "! $target уже существует и не симлинк — оставляю как есть"
  fi
done

# =============================================================================
# CLI-инструменты в ~/.local/bin
# =============================================================================
mkdir -p "$HOME/.local/bin"
# Снятые команды: install копирует только то, что есть в дереве, и не
# убирает лишнее. Без этой зачистки старая копия остаётся на PATH.
for _old in "$HOME/.local/bin"/brain-*; do
  [ -e "$_old" ] || continue
  _name="$(basename "$_old")"
  [ -f "$SCRIPT_DIR/runtime/bin/$_name" ] || rm -f "$_old"
done

# Одна установка вместо двух списков: раньше часть команд перечислялась
# поимённо здесь, часть — в add-power-features-brain.sh, и команда из одного
# списка не обновлялась при запуске другого скрипта. Так brain-run, brain-common
# и brain-launch однажды разъехались с деревом и сломали генерацию промпта.
# Список берётся из каталога: забыть команду больше нельзя.
_installed=0
for _cmd_path in "$SCRIPT_DIR"/runtime/bin/*; do
  [ -f "$_cmd_path" ] || continue
  case "$(basename "$_cmd_path")" in
    *.pyc|__pycache__) continue;;
  esac
  install -m 755 "$_cmd_path" "$HOME/.local/bin/$(basename "$_cmd_path")"
  _installed=$((_installed + 1))
done
[ "$_installed" -gt 0 ] || { echo "Нет исполняемых файлов в $SCRIPT_DIR/runtime/bin"; exit 1; }
echo "✓ CLI: установлено команд — $_installed"

# -----------------------------------------------------------------------------
# Схемы, шаблоны и ядро как пакет
# -----------------------------------------------------------------------------
mkdir -p "$HOME/.local/share/brain/schemas"
mkdir -p "$HOME/.local/share/brain/templates"
if [ -d "$SCRIPT_DIR/runtime/schemas" ]; then
  cp -R "$SCRIPT_DIR/runtime/schemas/." "$HOME/.local/share/brain/schemas/"
fi
if [ -d "$SCRIPT_DIR/runtime/templates/workspace" ]; then
  mkdir -p "$HOME/.local/share/brain/templates/workspace"
  cp -R "$SCRIPT_DIR/runtime/templates/workspace/." "$HOME/.local/share/brain/templates/workspace/"
fi

# Библиотека ставится один раз и editable: ровно одна копия — та, что в дереве.
echo ">>> Установка ядра как пакета (editable)"
if python3 -m pip install --user -e "$SCRIPT_DIR" --quiet 2>/dev/null; then
  echo "✓ pip install --user -e"
else
  # PEP 668: дистрибутивы помечают системный интерпретатор как externally-managed
  # и pip отказывается ставить в него что-либо. Ломать окружение
  # (--break-system-packages) ради этого нельзя, поэтому подключаем дерево так
  # же, как это сделал бы editable-install, — файлом .pth в user site-packages.
  python3 - "$SCRIPT_DIR" <<'PYEOF'
import site
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
target = Path(site.getusersitepackages())
target.mkdir(parents=True, exist_ok=True)
(target / "brain-runtime.pth").write_text(str(root / "runtime" / "lib") + "\n", encoding="utf-8")
print(f"✓ .pth в {target} (pip отказал: externally-managed)")
PYEOF
fi

# Старые копии удаляем: пока они лежат на месте, они участвуют в разрешении
# импорта и способны перебить дерево.
rm -rf "$HOME/.local/lib/brain" "$HOME/.local/share/brain/lib"



# Write-path hook in the data repo: commit of runtime/ there is rejected
# when BRAIN_SYSTEM_PATH points at a separate public checkout.
_install_data_write_path_hook() {
  local data_git="$BRAIN/.git/hooks"
  local guard="$SCRIPT_DIR/runtime/hooks/pre-commit-write-path"
  local hook="$data_git/pre-commit"
  [ -d "$BRAIN/.git" ] || return 0
  [ -x "$guard" ] || return 0
  mkdir -p "$data_git"
  if [ -f "$hook" ] && grep -q 'pre-commit-write-path' "$hook"; then
    return 0
  fi
  if [ -f "$hook" ]; then
    local tmp
    tmp="$(mktemp)"
    {
      printf '%s\n' '#!/usr/bin/env bash' 'set -e'
      printf '%s\n' "# write-path: system edits belong in BRAIN_SYSTEM_PATH"
      printf '%s\n' "_WRITE_GUARD=\"\${BRAIN_SYSTEM_PATH:-$SCRIPT_DIR}/runtime/hooks/pre-commit-write-path\""
      printf '%s\n' 'if [ -x "$_WRITE_GUARD" ]; then "$_WRITE_GUARD" || exit 1; fi'
      if grep -q '^#!/' "$hook"; then
        tail -n +2 "$hook"
      else
        cat "$hook"
      fi
    } > "$tmp"
    mv "$tmp" "$hook"
  else
    cat > "$hook" <<HOOK
#!/usr/bin/env bash
set -e
# write-path: system edits belong in BRAIN_SYSTEM_PATH
_WRITE_GUARD="\${BRAIN_SYSTEM_PATH:-$SCRIPT_DIR}/runtime/hooks/pre-commit-write-path"
if [ -x "\$_WRITE_GUARD" ]; then
  "\$_WRITE_GUARD" || exit 1
fi
HOOK
  fi
  chmod +x "$hook"
  echo "✓ write-path hook: $hook"
}
_install_data_write_path_hook

# Добавление .brain/index/ и .brain/vector/ в .gitignore самого брейна
if [ ! -f "$BRAIN/.gitignore" ]; then
  printf ".brain/index/\n.brain/vector/\n" > "$BRAIN/.gitignore"
else
  if ! grep -q ".brain/index/" "$BRAIN/.gitignore"; then
    echo ".brain/index/" >> "$BRAIN/.gitignore"
  fi
  if ! grep -q ".brain/vector/" "$BRAIN/.gitignore"; then
    echo ".brain/vector/" >> "$BRAIN/.gitignore"
  fi
fi

# ── Optional modules (Phase 7) ──────────────────────────────────────────────
if [ -n "$MODULES" ]; then
  declare -A MODULE_SCRIPTS=(
    [pm-finance]="add-pm-finance-brain.sh"
    [design-negotiator]="add-design-negotiator-brain.sh"
    [teams]="add-teams-brain.sh"
    [power-features]="add-power-features-brain.sh"
    [tax-boundaries]="refine-tax-boundaries.sh"
    [doctrine]="patch-brain-run-doctrine.sh"
  )
  IFS=',' read -ra MOD_LIST <<< "$MODULES"
  for m in "${MOD_LIST[@]}"; do
    m_trimmed="${m// /}"
    [ -z "$m_trimmed" ] && continue
    script="${MODULE_SCRIPTS[$m_trimmed]:-}"
    if [ -z "$script" ]; then
      echo "WARN: unknown module '$m_trimmed' (skip). Available: ${!MODULE_SCRIPTS[*]}"
      continue
    fi
    if [ ! -f "$SCRIPT_DIR/$script" ]; then
      echo "WARN: module script not found: $script (skip)"
      continue
    fi
    echo ">>> [module] $m_trimmed → $script"
    BRAIN_MODULE_INVOCATION=1 bash "$SCRIPT_DIR/$script"
  done
fi

# =============================================================================
echo
echo "==============================================================="
echo "  brain v2 готов: $BRAIN"
echo "==============================================================="
cat <<INFO

Команды (в \$HOME/.local/bin):
  brain-task       — задачи (next/list/take/release/complete/add)
  brain-lock       — атомарная блокировка
  brain-council    — оркестрация консилиума
  brain-run        — собрать промпт (память+роль+задача) для любого CLI
  brain-link       — присоединить память к проекту
  brain-validate   — проверить целостность (ссылки, источники)
  brain-ingest     — импортировать сырые данные
  brain-lint       — поиск сирот и чистка локов
  brain-index      — пересобрать поисковый индекс
  brain-search     — полнотекстовый поиск (BM25)
  brain-status     — статус оркестрации (read-only)
  brain-workspace  — folder-native workspaces (discover/tasks/next/take/complete)
  brain-review-cycle — регулярный reviewer-цикл: отчёт + corrective tasks
  brain-queue-cycle — daily launch proposals for dashboard confirmation
  brain-provider   — статус и явное обновление локального provider health cache
  brain-federation — read-only preflight для federation/sync изменений
  brain-orchestrator — wrapper с fallback на другой CLI при quota/context-limit

Пример рабочего цикла:

  # 1. Архитектор декомпозирует
  brain-run --role architect --task t-2026-05-01-bootstrap-wiki | claude -p

  # 2. Параллельно: разработчик и ревьюер на разных моделях
  AGENT_DEV="dev-$(uuidgen | head -c4)"
  brain-task take t-... --as \$AGENT_DEV
  brain-run --role developer --task t-... --agent-id \$AGENT_DEV | claude
  # ... в другом терминале ...
  brain-run --role reviewer  --task t-... --agent-id rev-xx     | gemini

  # 3. Консилиум
  brain-council start t-2026-05-01-pick-llm-stack
  # запусти каждую роль в свой CLI как покажет команда выше
  brain-council status t-2026-05-01-pick-llm-stack
  brain-council synthesize t-2026-05-01-pick-llm-stack
  brain-run --role arbiter --task t-... --council | claude -p

Если \$HOME/.local/bin не в PATH:
  echo 'export PATH="\$HOME/.local/bin:\$PATH"' >> ~/.zshrc

Опционально для Obsidian-aware agents:
  bash "$SCRIPT_DIR/install-obsidian-skills.sh"
  # затем перезапусти Codex, чтобы skill registry перечитался

INFO
