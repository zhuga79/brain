#!/usr/bin/env bash
# Test: dashboard search — progress indicator + API results + timeout payload.
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying dashboard search UI + API"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
export PYTHONPATH="$PROJECT_ROOT/runtime/lib"
mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/wiki" "$BRAIN_PATH/.brain"
printf '# Active Tasks\n' > "$BRAIN_PATH/tasks/active.md"
printf '# Done\n' > "$BRAIN_PATH/tasks/done.md"
printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"
# Real brain-search needs a built index; seed a searchable page and rebuild.
cat > "$BRAIN_PATH/wiki/index.md" <<'IDX'
# Wiki Index
- [[operator-dashboard]]
IDX
cat > "$BRAIN_PATH/wiki/operator-dashboard.md" <<'PG'
# Operator Dashboard
The operator dashboard shows tasks, launches and provider health.
PG
brain-index rebuild >/dev/null 2>&1 || true

brain-dashboard serve --port 19995 &
srv_pid=$!
trap 'kill $srv_pid 2>/dev/null || true' EXIT
sleep 1

# (a) progress indicator element rendered
page="$(curl -s --noproxy '*' "http://127.0.0.1:19995/")"
grep -q 'id="search-progress"' <<< "$page" || { echo "FAILED: search-progress element missing"; exit 1; }
echo "OK: progress indicator rendered"

# (b) /api/search returns results JSON
curl -s --noproxy '*' "http://127.0.0.1:19995/api/search?q=dashboard&mode=bm25" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert isinstance(d.get('results'), list), f'results should be a list: {str(d)[:200]}'
assert d['results'], f'expected a match for seeded page: {str(d)[:200]}'
print('OK: API returned results for a real indexed query')
" || { echo "FAILED: API search response invalid"; exit 1; }

# (c) search JS wired to the progress indicator + timeout handling
python3 -c "
from brain_dashboard.render import assets
s = assets.SEARCH_SCRIPT
assert 'search-progress' in s, 'JS must reference search-progress'
assert 'timed_out' in s, 'JS must handle timed_out'
print('OK: search JS wired (progress + timeout)')
" || { echo "FAILED: search JS not wired"; exit 1; }

python3 -c "
from brain_dashboard.render import assets
s = assets.SEARCH_SCRIPT
assert 'pathTd.textContent = r.path;' in s, 'path must be rendered as text'
assert 'strong.textContent = r.title;' in s, 'title must be rendered as text'
assert 'span.textContent = r.snippet || \"\";' in s, 'snippet must be rendered as text'
assert 'html +=' not in s, 'search results must not be built through HTML concatenation'
assert 'resDiv.innerHTML = html' not in s, 'search results must not be injected via innerHTML'
print('OK: search JS escapes result fields')
" || { echo "FAILED: search JS XSS protection missing"; exit 1; }

echo ">>> dashboard search tests passed"
