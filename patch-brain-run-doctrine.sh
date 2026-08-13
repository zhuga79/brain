#!/usr/bin/env bash
# patch-brain-run-doctrine.sh
# Обновляет brain-run так, чтобы он автоматически подтягивал в промпт
# те doctrine-файлы, которые упомянуты в role-файле текущей роли.
#
# Это критично: без этого агент видит ссылку "см. doctrine/tax-boundaries.md",
# но физически файл в контекст не попадает (если CLI не имеет file access).

set -euo pipefail
# ── Phase 7 deprecation notice ────────────────────────────────────────────────
# Direct invocation of this script is deprecated. Prefer:
#   bash setup-brain-v2.sh --module <name>
# Setting BRAIN_MODULE_INVOCATION=1 (done by setup-brain-v2.sh) suppresses this.
if [ -z "${BRAIN_MODULE_INVOCATION:-}" ]; then
  echo "WARN: legacy invocation of $(basename "$0"). Use: setup-brain-v2.sh --module <name>" >&2
fi


SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin/brain-run"
[ ! -f "$BIN" ] && { echo "Нет $BIN — запусти setup-brain-v2.sh"; exit 1; }

RUNTIME_BRAIN_COMMON="$SCRIPT_DIR/runtime/bin/brain-common"
[ ! -f "$RUNTIME_BRAIN_COMMON" ] && { echo "Нет $RUNTIME_BRAIN_COMMON"; exit 1; }
install -m 755 "$RUNTIME_BRAIN_COMMON" "$HOME/.local/bin/brain-common"

RUNTIME_BRAIN_RUN="$SCRIPT_DIR/runtime/bin/brain-run"
[ ! -f "$RUNTIME_BRAIN_RUN" ] && { echo "Нет $RUNTIME_BRAIN_RUN"; exit 1; }
install -m 755 "$RUNTIME_BRAIN_RUN" "$BIN"

echo "✓ brain-run обновлён — теперь автоматически подгружает doctrine"
echo
echo "Проверка:"
echo "  brain-run --role tax-advisor --task t-... | grep -c '4 этапа'"
echo "  → должно быть > 0 (содержимое tax-boundaries.md в промпте)"
