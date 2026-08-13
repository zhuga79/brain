#!/usr/bin/env bash
# 38-frontmatter.sh — YAML-ish frontmatter parser edge-case tests
# Tests parse_frontmatter via the brain_wiki package (post Phase 14.1 split).
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Testing brain_wiki.parse_frontmatter edge cases"

PY_LIB="$HOME/.local/share/brain/lib"

run_py() {
    python3 -c "
import sys
sys.path.insert(0, '$PY_LIB')
from brain_wiki import parse_frontmatter, format_frontmatter, as_list, as_bool
$1
"
}

# ── Test 1: Normal frontmatter ────────────────────────────────────────────────
echo ">>> Test 1: normal frontmatter"
run_py "
fm, body = parse_frontmatter('---\ntitle: Hello\ntype: concept\n---\nbody text')
assert fm == {'title': 'Hello', 'type': 'concept'}, f'FAIL fm={fm}'
assert body.strip() == 'body text', f'FAIL body={repr(body)}'
print('OK')
" | grep -q "OK" || { echo "FAILED: Test 1 normal frontmatter"; exit 1; }

# ── Test 2: No frontmatter ────────────────────────────────────────────────────
echo ">>> Test 2: no frontmatter"
run_py "
fm, body = parse_frontmatter('no frontmatter here')
assert fm == {}, f'FAIL fm={fm}'
print('OK')
" | grep -q "OK" || { echo "FAILED: Test 2 no frontmatter"; exit 1; }

# ── Test 3: Colon in value ────────────────────────────────────────────────────
echo ">>> Test 3: colon in value"
run_py "
fm, body = parse_frontmatter('---\nurl: https://example.com/path\n---\n')
assert fm.get('url') == 'https://example.com/path', f'FAIL fm={fm}'
print('OK')
" | grep -q "OK" || { echo "FAILED: Test 3 colon in value"; exit 1; }

# ── Test 4: Comment lines skipped ────────────────────────────────────────────
echo ">>> Test 4: comment lines in frontmatter"
run_py "
fm, body = parse_frontmatter('---\n# comment line\ntitle: Test\n---\n')
assert fm.get('title') == 'Test', f'FAIL fm={fm}'
assert len(fm) == 1, f'FAIL extra keys: {fm}'
print('OK')
" | grep -q "OK" || { echo "FAILED: Test 4 comment lines"; exit 1; }

# ── Test 5: Missing closing --- ───────────────────────────────────────────────
echo ">>> Test 5: missing closing ---"
run_py "
fm, body = parse_frontmatter('---\ntitle: Broken\n')
assert fm == {}, f'FAIL fm={fm}'
print('OK')
" | grep -q "OK" || { echo "FAILED: Test 5 missing trailer"; exit 1; }

# ── Test 6: Boolean values ────────────────────────────────────────────────────
echo ">>> Test 6: boolean values"
run_py "
fm, body = parse_frontmatter('---\nprotected: true\ndraft: false\n---\n')
assert fm.get('protected') is True, f'FAIL protected={fm.get(\"protected\")}'
assert fm.get('draft') is False, f'FAIL draft={fm.get(\"draft\")}'
print('OK')
" | grep -q "OK" || { echo "FAILED: Test 6 booleans"; exit 1; }

# ── Test 7: List values ───────────────────────────────────────────────────────
echo ">>> Test 7: list values"
run_py "
fm, body = parse_frontmatter('---\ntags: [python, brain, wiki]\n---\n')
assert fm.get('tags') == ['python', 'brain', 'wiki'], f'FAIL tags={fm.get(\"tags\")}'
print('OK')
" | grep -q "OK" || { echo "FAILED: Test 7 lists"; exit 1; }

# ── Test 8: Empty list ────────────────────────────────────────────────────────
echo ">>> Test 8: empty list"
run_py "
fm, body = parse_frontmatter('---\ntags: []\n---\n')
assert fm.get('tags') == [], f'FAIL tags={fm.get(\"tags\")}'
print('OK')
" | grep -q "OK" || { echo "FAILED: Test 8 empty list"; exit 1; }

# ── Test 9: --- inside body not confused for trailer ─────────────────────────
echo ">>> Test 9: --- inside body"
run_py "
content = '---\ntitle: Doc\n---\nbody text\n---\nmore text'
fm, body = parse_frontmatter(content)
assert fm.get('title') == 'Doc', f'FAIL fm={fm}'
assert '---' in body, f'FAIL body missing inner ---: {repr(body)}'
print('OK')
" | grep -q "OK" || { echo "FAILED: Test 9 --- inside body"; exit 1; }

# ── Test 10: as_list and as_bool helpers ──────────────────────────────────────
echo ">>> Test 10: as_list / as_bool helpers"
run_py "
assert as_list(None) == []
assert as_list('') == []
assert as_list('single') == ['single']
assert as_list(['a', 'b']) == ['a', 'b']
assert as_bool(True) is True
assert as_bool('yes') is True
assert as_bool('false') is False
assert as_bool(0) is False
print('OK')
" | grep -q "OK" || { echo "FAILED: Test 10 as_list/as_bool"; exit 1; }

echo ">>> All 10 frontmatter tests passed"
