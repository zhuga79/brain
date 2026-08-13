#!/usr/bin/env bash
# case: health-probe
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-provider probe"

rm -f "$BRAIN_PATH/.provider-health.json"

# 1. Test probe all
probe_all=$(brain-provider probe)

if [ ! -f "$BRAIN_PATH/.provider-health.json" ]; then
  echo "FAILED: .provider-health.json not created"
  exit 1
fi

if ! grep -q '"checked_at"' "$BRAIN_PATH/.provider-health.json"; then
  echo "FAILED: checked_at not in cache"
  exit 1
fi

# 2. Test TTL (should skip)
probe_ttl=$(brain-provider probe)
if ! echo "$probe_ttl" | grep -q "probe skipped (within TTL)"; then
  echo "FAILED: probe did not skip within TTL"
  exit 1
fi

# 3. Test probe role
rm -f "$BRAIN_PATH/.provider-health.json"
probe_role=$(brain-provider probe --role architect)

if echo "$probe_role" | grep -q "gemini-3-flash"; then
  echo "FAILED: probe role checked developer model when it shouldn't have"
  exit 1
fi

# Verify JSON cache is valid
if ! python3 -c 'import json, sys; json.load(open(sys.argv[1]))' "$BRAIN_PATH/.provider-health.json"; then
  echo "FAILED: cache is not valid JSON"
  exit 1
fi

echo "health-probe OK"
