#!/usr/bin/env bash
# case: diversify — рецензент не идёт к провайдеру автора
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying diversification rule is applied by the launcher"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1

mkdir -p "$BRAIN_PATH/config"
cat > "$BRAIN_PATH/config/routing.json" <<'JSON'
{
  "version": 2,
  "defaults": { "cli": "claude" },
  "providers": {
    "claude":   { "command": "claude", "model_flag": "--model {model}", "enabled": true },
    "opencode": { "command": "opencode run", "model_flag": "-m opencode/{model}", "enabled": true }
  },
  "profiles": {
    "review": [
      { "rank": 1, "provider": "claude", "model": "opus" },
      { "rank": 2, "provider": "opencode", "model": "deepseek" }
    ]
  },
  "roles": {
    "reviewer": { "profile": "review", "diversify_from_author": true },
    "developer": { "profile": "review" }
  }
}
JSON

# ── 1. Совпадение провайдеров: рецензент опускается по рангу ──
out="$(brain-provider cli --role reviewer --author-provider claude)"
[ "$out" = "opencode run -m opencode/deepseek" ] || {
  echo "FAILED: рецензент остался у провайдера автора: $out"
  exit 1
}
echo "OK: при совпадении провайдер меняется"

# ── 2. Расхождение: правило ничего не меняет ──
out="$(brain-provider cli --role reviewer --author-provider opencode)"
[ "$out" = "claude --model opus" ] || {
  echo "FAILED: при разных провайдерах маршрут изменился: $out"
  exit 1
}
echo "OK: при расхождении маршрут прежний"

# ── 3. Роль без флага провайдера автора не замечает ──
out="$(brain-provider cli --role developer --author-provider claude)"
[ "$out" = "claude --model opus" ] || {
  echo "FAILED: роль без diversify_from_author подчинилась правилу: $out"
  exit 1
}
echo "OK: правило действует только на помеченные роли"

# ── 4. bash-слой передаёт провайдера автора ──
# shellcheck source=/dev/null
source "$PROJECT_ROOT/runtime/bin/brain-common"
author="$(provider_of_cli "$(cli_for_role developer "" "")")"
reviewer_cli="$(cli_for_role reviewer "" "$author")"
[ "$(provider_of_cli "$reviewer_cli")" != "$author" ] || {
  echo "FAILED: cli_for_role не применил правило: автор=$author рецензент=$reviewer_cli"
  exit 1
}
echo "OK: cli_for_role применяет правило"

grep -q 'author_provider' "$PROJECT_ROOT/runtime/bin/brain-council" || {
  echo "FAILED: brain-council не передаёт провайдера автора"
  exit 1
}
echo "OK: brain-council передаёт провайдера автора"

echo ">>> diversification checks passed"
