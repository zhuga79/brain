#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-provider CLI contract"
rm -f "$BRAIN_PATH/.provider-health.json"

# Политика маршрутизации живёт в config/routing.json; wiki/ остался лишь
# фолбэком для деревьев без миграции.
# Фабрика общая: подменённую конфигурацию возвращаем на выходе, иначе
# следующие кейсы видят чужую политику и падают не по своей причине.
mkdir -p "$BRAIN_PATH/config"
_ORIG_ROUTING="$(mktemp)"
[ -f "$BRAIN_PATH/config/routing.json" ] && cp "$BRAIN_PATH/config/routing.json" "$_ORIG_ROUTING"
trap '[ -s "$_ORIG_ROUTING" ] && cp "$_ORIG_ROUTING" "$BRAIN_PATH/config/routing.json"; rm -f "$_ORIG_ROUTING"' EXIT
cat >"$BRAIN_PATH/config/routing.json" <<JSON
{
  "version": 2,
  "updated": "2026-05-06",
  "source": "provider-smoke",
  "roles": {
    "developer": [
      {
        "rank": 1,
        "provider": "probe",
        "model": "ok",
        "command": "/bin/true",
        "use_for": "smoke probe"
      }
    ]
  },
  "routes": {}
}
JSON

brain-provider status --json >/tmp/brain_provider_status.json
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_provider_status.json"))
assert data["roles"]["developer"]["preferred"]["key"] == "probe/ok", data
assert data["roles"]["developer"]["preferred"]["status"] == "unknown", data
PYEOF

[ ! -f "$BRAIN_PATH/.provider-health.json" ] || {
  echo "FAILED: status created health cache"
  exit 1
}

brain-provider refresh --provider probe --model ok >/tmp/brain_provider_dryrun.txt
grep -q "dry-run" /tmp/brain_provider_dryrun.txt || {
  echo "FAILED: refresh without --yes did not report dry-run"
  cat /tmp/brain_provider_dryrun.txt
  exit 1
}
[ ! -f "$BRAIN_PATH/.provider-health.json" ] || {
  echo "FAILED: dry-run created health cache"
  exit 1
}

brain-provider mark --provider probe --model ok --status rate-limited \
  --reason "HTTP 429 RESOURCE_EXHAUSTED" --yes --json >/tmp/brain_provider_mark.json
python3 - <<'PYEOF'
import json, os, pathlib
cache = pathlib.Path(os.environ["BRAIN_PATH"]) / ".provider-health.json"
data = json.loads(cache.read_text())
item = data["items"]["probe/ok"]
assert item["status"] == "rate-limited", data
assert item["source"] == "manual", data
assert item["reason"] == "HTTP 429 RESOURCE_EXHAUSTED", data
PYEOF

brain-provider clear --provider probe --model ok --yes --json >/tmp/brain_provider_clear.json
python3 - <<'PYEOF'
import json, os, pathlib
cache = pathlib.Path(os.environ["BRAIN_PATH"]) / ".provider-health.json"
data = json.loads(cache.read_text())
assert "probe/ok" not in data.get("items", {}), data
PYEOF

cat >"$BRAIN_PATH/.provider-health.json" <<JSON
{
  "version": 1,
  "updated": "2026-05-06T00:00:00Z",
  "items": {
    "other/model": {
      "provider": "other",
      "model": "model",
      "status": "auth-required",
      "source": "manual",
      "reason": "kept",
      "checked_at": "2026-05-06T00:00:00Z"
    }
  }
}
JSON

brain-provider refresh --provider probe --model ok --yes --json >/tmp/brain_provider_refresh.json
python3 - <<'PYEOF'
import json, os, pathlib
cache = pathlib.Path(os.environ["BRAIN_PATH"]) / ".provider-health.json"
data = json.loads(cache.read_text())
assert data["items"]["other/model"]["reason"] == "kept", data
item = data["items"]["probe/ok"]
assert item["provider"] == "probe", data
assert item["model"] == "ok", data
assert item["status"] == "available", data
assert item["source"] == "probe", data
assert item["reason"], data
assert item["checked_at"], data
PYEOF

cat >"$BRAIN_PATH/.provider-health.json" <<'BROKEN'
{"items":
BROKEN
set +e
brain-provider mark --provider probe --model ok --status available --reason ok --yes >/tmp/brain_provider_invalid.out 2>/tmp/brain_provider_invalid.err
invalid_rc=$?
set -e
[ "$invalid_rc" -ne 0 ] || {
  echo "FAILED: mark accepted invalid existing cache"
  exit 1
}
grep -qi "invalid" /tmp/brain_provider_invalid.err || {
  echo "FAILED: invalid cache error did not mention invalid"
  cat /tmp/brain_provider_invalid.err
  exit 1
}
grep -q '{"items":' "$BRAIN_PATH/.provider-health.json" || {
  echo "FAILED: invalid cache was overwritten"
  exit 1
}

echo "brain-provider CLI OK"
