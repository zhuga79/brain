#!/usr/bin/env bash
# case: routing-validate — brain-validate ловит дыры в маршрутизации
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-validate catches routing holes"

config="$BRAIN_PATH/config/routing.json"
probe_role="$BRAIN_PATH/roles/испытательная-роль.md"
mkdir -p "$BRAIN_PATH/config" "$BRAIN_PATH/roles"

# Фабрика общая для всех кейсов: свою конфигурацию мы подменяем, но обязаны
# вернуть исходную. Синтезированная в конце кейса покрывает только те роли,
# что были на тот момент, и следующий кейс, добавивший роль, падал на
# «роль без разрешимой записи».
ORIGINAL_CONFIG="$(mktemp)"
[ -f "$config" ] && cp "$config" "$ORIGINAL_CONFIG"
restore_config() {
  if [ -s "$ORIGINAL_CONFIG" ]; then
    cp "$ORIGINAL_CONFIG" "$config"
  fi
  rm -f "$probe_role"
  # Возвращаем и проекцию: страница решения должна соответствовать
  # восстановленной конфигурации, а не той, что была в середине кейса.
  brain-provider render-doc >/dev/null 2>&1 || true
}
trap 'restore_config; rm -f "$ORIGINAL_CONFIG"' EXIT

# Конфигурация покрывает ровно те роли, что лежат в дереве: проверка покрытия
# не должна зависеть от того, сколько ролей завели помимо кейса.
write_config() {
  python3 - "$BRAIN_PATH" <<'PY'
import json, sys
from pathlib import Path
brain = Path(sys.argv[1])
roles = sorted(p.stem for p in (brain / "roles").glob("*.md"))
cfg = {
    "version": 2,
    "defaults": {"cli": "claude"},
    "providers": {"claude": {"command": "claude", "model_flag": "--model {model}", "enabled": True}},
    "profiles": {"universal": [{"rank": 1, "provider": "claude", "model": "sonnet"}]},
    "roles": {r: {"profile": "universal"} for r in roles},
}
(brain / "config" / "routing.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
PY
  # Проза страницы решения — проекция конфигурации: раз мы её подменили,
  # блок надо перерисовать, иначе валидатор справедливо укажет на расхождение.
  brain-provider render-doc >/dev/null 2>&1 || true
}

# Ошибки маршрутизации отличаем от прочих: в песочнице есть свои жалобы
# (например, на UI/UX-скиллы), и они к этому кейсу отношения не имеют.
routing_issues() {
  brain-validate 2>&1 | grep -E "routing\.json|остался после миграции|роль без разрешимой записи" || true
}

# ── База ──
write_config
found="$(routing_issues)"
[ -z "$found" ] || { echo "FAILED: целая конфигурация вызвала жалобу:"; echo "$found"; exit 1; }
echo "OK: целая конфигурация проходит"

expect_error() {
  local label="$1" needle="$2"
  local out
  out="$(routing_issues)"
  grep -q "$needle" <<< "$out" || {
    echo "FAILED [$label]: нет сообщения про '$needle'"
    echo "${out:-<пусто>}"
    exit 1
  }
  brain-validate >/dev/null 2>&1 && {
    echo "FAILED [$label]: brain-validate завершился успешно"
    exit 1
  }
  echo "OK: $label"
}

mutate() {
  python3 - "$config" "$1" <<'PY'
import json, sys
path, what = sys.argv[1], sys.argv[2]
d = json.load(open(path))
if what == "unknown-profile":
    next(iter(d["roles"].values()))["profile"] = "нет-такого"
elif what == "unknown-provider":
    d["profiles"]["universal"][0]["provider"] = "неизвестный"
elif what == "duplicate-rank":
    d["profiles"]["universal"].append({"rank": 1, "provider": "claude", "model": "opus"})
elif what == "bad-version":
    d["version"] = 99
json.dump(d, open(path, "w"), ensure_ascii=False)
PY
}

# ── 1. Роль без разрешимой записи ──
write_config
printf '# Испытательная роль\n' > "$probe_role"
expect_error "роль без записи уходила бы в defaults.cli" "роль без разрешимой записи"
rm -f "$probe_role"

# ── 2. Ссылка на несуществующий профиль ──
write_config; mutate unknown-profile
expect_error "несуществующий профиль" "не существует"

# ── 3. Провайдер, не описанный в providers ──
write_config; mutate unknown-provider
expect_error "провайдер вне providers" "не описан в providers"

# ── 4. Повторяющийся rank внутри профиля ──
write_config; mutate duplicate-rank
expect_error "повторяющийся rank" "повторяющийся rank"

# ── 5. Неизвестная версия формата ──
write_config; mutate bad-version
expect_error "неизвестная версия" "ожидается"

# ── 6. Нечитаемый конфиг ──
printf '{ сломано' > "$config"
expect_error "нечитаемый конфиг" "не читается"

# ── 7. Файлы, оставшиеся после миграции ──
write_config
printf '{}' > "$BRAIN_PATH/wiki/provider-matrix.json"
expect_error "wiki/provider-matrix.json остался" "остался после миграции"
rm -f "$BRAIN_PATH/wiki/provider-matrix.json"

write_config
printf 'cli_for_developer="claude"\n' > "$BRAIN_PATH/.cli-mapping.sh"
expect_error ".cli-mapping.sh остался" "остался после миграции"
rm -f "$BRAIN_PATH/.cli-mapping.sh"

# ── 8. Возврат в исходное состояние ──
restore_config
found="$(routing_issues)"
[ -z "$found" ] || { echo "FAILED: после восстановления остались жалобы:"; echo "$found"; exit 1; }
echo "OK: восстановленная конфигурация проходит"

echo ">>> routing validation checks passed"
