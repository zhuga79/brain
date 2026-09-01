#!/usr/bin/env bash
# install-brain-mcp.sh — установка MCP-сервера поверх ~/brain/.
#
# Поднимает FastMCP-сервер, который экспортирует операции brain как tools.
# После этого LLM-агенты с MCP-поддержкой (Claude Code, etc.) могут вызывать
# take_task / acquire_lock / add_council_opinion / search_wiki и т.д. напрямую
# вместо shell.
#
# Что делает:
#   1. Создаёт ~/.local/share/brain-mcp/ с Python venv и server.py
#   2. Создаёт launcher ~/.local/bin/brain-mcp
#   3. Печатает инструкции по подключению к Claude Code / другим клиентам

set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BRAIN="${BRAIN_PATH:-$HOME/brain}"
# Каталог установки и путь лаунчера переопределяются теми же переменными,
# что читают brain-status, setup-brain-v2.sh и сам лаунчер. Без этого
# установщик был единственным, кто умел писать только в боевую установку, —
# проверить его, не трогая рабочий MCP оператора, было нечем.
MCP_DIR="${BRAIN_MCP_DIR:-$HOME/.local/share/brain-mcp}"
LAUNCHER_PATH="${BRAIN_MCP_LAUNCHER:-$HOME/.local/bin/brain-mcp}"
PACKAGING_TOOL="$SCRIPT_DIR/runtime/mcp/packaging.py"

[ ! -f "$BRAIN/MEMORY.md" ] && { echo "Сначала setup-brain-v2.sh"; exit 1; }
[ ! -f "$PACKAGING_TOOL" ] && { echo "Не найден $PACKAGING_TOOL"; exit 1; }

mkdir -p "$MCP_DIR"
mkdir -p "$(dirname "$LAUNCHER_PATH")"

# =============================================================================
# Python venv + FastMCP
# =============================================================================
need_pip=0
pip_skipped=0
if [ ! -d "$MCP_DIR/.venv" ]; then
  echo ">>> Создаю venv в $MCP_DIR/.venv"
  python3 -m venv "$MCP_DIR/.venv"
  need_pip=1
fi

if [ "${BRAIN_MCP_SKIP_PIP:-0}" = "1" ]; then
  echo ">>> Пропускаю pip install (BRAIN_MCP_SKIP_PIP=1)"
  # SKIP_PIP запрещает pip безусловно, включая только что созданный venv —
  # иначе флаг бесполезен ровно там, где он нужен: на чистой установке.
  need_pip=0
  pip_skipped=1
elif [ "${BRAIN_MCP_FORCE_PIP:-0}" = "1" ]; then
  need_pip=1
fi

if [ "$need_pip" -eq 1 ]; then
  echo ">>> Устанавливаю fastmcp"
  # В окружениях с прокси часто выставлены HTTP(S)_PROXY на локальный сокет.
  # Для установки MCP зависимостей надёжнее сбросить proxy-переменные на время pip.
  env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u NO_PROXY -u no_proxy -u ALL_PROXY -u all_proxy \
    "$MCP_DIR/.venv/bin/pip" install --quiet --upgrade pip
  env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u NO_PROXY -u no_proxy \
    -u ALL_PROXY -u all_proxy "$MCP_DIR/.venv/bin/pip" install --quiet "mcp>=1.0.0" "fastmcp>=0.4.0" 2>&1 | tail -3 || {
    # fallback: только mcp
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u NO_PROXY -u no_proxy \
      -u ALL_PROXY -u all_proxy "$MCP_DIR/.venv/bin/pip" install --quiet "mcp>=1.0.0"
  }
elif [ "$pip_skipped" -eq 0 ]; then
  echo ">>> Использую существующие MCP dependencies (.venv уже есть)"
fi

# =============================================================================
# Install canonical runtime tree
# =============================================================================

echo ">>> Синхронизирую canonical MCP runtime tree"
python3 "$PACKAGING_TOOL" install --system-root "$SCRIPT_DIR" --install-root "$MCP_DIR" >/dev/null
python3 "$PACKAGING_TOOL" verify --system-root "$SCRIPT_DIR" --install-root "$MCP_DIR" >/dev/null

# =============================================================================
# Launcher script
# =============================================================================

LAUNCHER_SRC="$SCRIPT_DIR/runtime/bin/brain-mcp"
[ ! -f "$LAUNCHER_SRC" ] && { echo "Не найден $LAUNCHER_SRC"; exit 1; }
install -m 755 "$LAUNCHER_SRC" "$LAUNCHER_PATH"

# =============================================================================
# Smoke test
# =============================================================================
# Дерево и launcher уже на месте — это структурная установка, она удалась.
# Импорт server и `--help` нужны MCP-зависимости в venv. Если pip был пропущен
# (BRAIN_MCP_SKIP_PIP) и зависимостей нет — smoke не выполняем, но говорим об
# этом точно: чего не хватает и как доустановить. Если pip отработал, а import
# всё равно падает — это настоящий отказ.
deps_ok=0
if "$MCP_DIR/.venv/bin/python" -c "import mcp" >/dev/null 2>&1; then
  deps_ok=1
fi

echo
if [ "$deps_ok" -eq 1 ]; then
  echo ">>> Smoke test: импорт и --help"
  "$MCP_DIR/.venv/bin/python" -c "
import sys, asyncio
sys.path.insert(0, '$MCP_DIR/runtime/lib')
sys.path.insert(0, '$MCP_DIR/runtime/mcp')
import server
names = [getattr(tool, '__name__', 'tool') for tool in getattr(server.mcp, '_tools', [])]
print(f'  ✓ Импорт ОК. tools зарегистрированы: {len(names)}')
print('  Примеры:', names[:8])
" 2>&1
  "$LAUNCHER_PATH" --help >/dev/null
  echo "  ✓ Launcher --help ОК"
elif [ "$pip_skipped" -eq 1 ]; then
  echo ">>> Smoke пропущен: в $MCP_DIR/.venv нет MCP-зависимостей (BRAIN_MCP_SKIP_PIP=1)"
  echo "    Дерево и launcher установлены. Перед использованием сервера:"
  echo "      '$MCP_DIR/.venv/bin/pip' install 'mcp>=1.0.0' 'fastmcp>=0.4.0'"
  echo "    или переустановить без BRAIN_MCP_SKIP_PIP."
else
  echo "!!! MCP-зависимости не установились: 'import mcp' падает после pip." >&2
  echo "    venv: $MCP_DIR/.venv" >&2
  exit 1
fi

echo
echo "==============================================================="
echo "  MCP-сервер установлен"
echo "==============================================================="
cat <<INFO

Сервер: $MCP_DIR/runtime/mcp/server.py
Запуск: brain-mcp                  (из терминала, для отладки)

## Подключение к Claude Code

Один раз:
  claude mcp add brain "$LAUNCHER_PATH"

После этого в любой Claude Code сессии будут доступны tools:
  brain__list_tasks
  brain__get_next_task
  brain__take_task
  brain__complete_task
  brain__acquire_lock
  brain__add_council_opinion
  brain__synthesize_council
  brain__search_wiki
  brain__write_wiki_page
  brain__get_role
  brain__get_doctrine
  brain__add_task
  ... и ещё ~25 операций.

## Подключение к другим клиентам

Любой MCP-совместимый клиент. Команда сервера: brain-mcp (без аргументов,
читает с stdin, пишет в stdout — стандартный MCP stdio transport).

## Что это даёт vs CLI

Было (shell):
  brain-task take t-... --as agent
  brain-run --role x --task t-... | claude
Теперь (для MCP-агента):
  агент сам вызывает brain__take_task(...) и brain__add_council_opinion(...)
  без выхода в shell. Можно совмещать оба подхода — данные те же файлы.

## Тонкости

- MCP-сервер и shell-команды РАБОТАЮТ С ОДНИМИ И ТЕМИ ЖЕ ФАЙЛАМИ.
  Можно одновременно использовать brain-task в терминале и MCP-tools
  в агенте — состояние согласовано через файловую систему + .locks/.
- Все операции делают git auto-commit, как и shell.
- Логирование в wiki/log.md — общее для shell и MCP.

INFO
