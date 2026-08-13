#!/usr/bin/env bash
# case: dashboard-providers
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-dashboard Provider cards"

out="$BRAIN_PATH/../dashboard_providers.html"

# Политика маршрутизации живёт в файле, а не в коде: вшитый дефолт больше не
# подставляет роли, поэтому карточки берутся из конфигурации.
mkdir -p "$BRAIN_PATH/config"
cat > "$BRAIN_PATH/config/routing.json" <<'JSON'
{
  "version": 2,
  "updated": "2026-08-10",
  "roles": {
    "architect":  [{"rank": 1, "provider": "claude", "model": "opus-5",   "command": "claude"}],
    "developer":  [{"rank": 1, "provider": "claude", "model": "sonnet-5", "command": "claude"}],
    "reviewer":   [{"rank": 1, "provider": "codex",  "model": "gpt-5.5",  "command": "codex"}],
    "researcher": [{"rank": 1, "provider": "claude", "model": "sonnet-5", "command": "claude"}],
    "linter":     [{"rank": 1, "provider": "claude", "model": "haiku-4.5","command": "claude"}],
    "arbiter":    [{"rank": 1, "provider": "codex",  "model": "gpt-5.5",  "command": "codex"}]
  }
}
JSON

brain-dashboard export --out "$out"

# Считаем сами карточки, а не любое упоминание класса: правило в стилях
# тоже содержит provider-card и давало бы единицу на пустой матрице.
card_count=$(grep -o "card provider-card" "$out" | wc -l)
if [ "$card_count" -lt 6 ]; then
  echo "FAILED: Expected at least 6 provider cards, found $card_count"
  grep -C 20 'id="providers"' "$out"
  exit 1
fi
echo "OK: $card_count provider cards rendered from config/routing.json"

if ! grep -q "Probe All" "$out"; then
  echo "FAILED: 'Probe All' button missing"
  exit 1
fi

# Без конфигурации дашборд обязан сказать, что маршрутизация не настроена, а не
# показать роли из вшитого списка: «не настроено» и «настроено так» — разные
# состояния, и подмена одного другим прячет поломку.
rm -f "$BRAIN_PATH/config/routing.json" "$BRAIN_PATH/wiki/provider-matrix.json"
brain-dashboard export --out "$out"

if [ "$(grep -c "card provider-card" "$out")" -ne 0 ]; then
  echo "FAILED: роли отрисованы без файла маршрутизации"
  grep -C 10 'id="providers"' "$out"
  exit 1
fi
if ! grep -q "No providers configured" "$out"; then
  echo "FAILED: дашборд не сообщил, что маршрутизация не настроена"
  exit 1
fi
if ! grep -q "routing.json" "$out"; then
  echo "FAILED: не названа причина — отсутствующий файл маршрутизации"
  grep -C 5 'id="providers"' "$out"
  exit 1
fi
echo "OK: отсутствие конфигурации показано как отсутствие, а не как пустая политика"

echo "dashboard-providers OK"
