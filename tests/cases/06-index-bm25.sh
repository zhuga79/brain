#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying machine index and BM25 search"
cat > "$BRAIN_PATH/wiki/search-topic.md" <<EOF
---
title: Search Topic
type: concept
created: 2026-05-02
updated: 2026-05-02
curation: agent
protected: false
source_policy: advisory
tags: [search]
sources: [raw/demo-source.md]
related: []
---

# Search Topic

This page contains rarebrainterm and links to [[decision-search]].
EOF
cat > "$BRAIN_PATH/wiki/decision-search.md" <<EOF
---
title: Decision Search
type: decision
created: 2026-05-02
updated: 2026-05-02
curation: agent
protected: false
source_policy: required
tags: [decision]
sources: [raw/demo-source.md]
related: []
---

# Decision Search

Decision page for index tests.
EOF

brain-index rebuild > /dev/null
[ -f "$BRAIN_PATH/.brain/index/pages.json" ] || { echo "FAILED: pages.json not generated"; exit 1; }
[ -f "$BRAIN_PATH/.brain/index/links.json" ] || { echo "FAILED: links.json not generated"; exit 1; }
[ -f "$BRAIN_PATH/.brain/index/sources.json" ] || { echo "FAILED: sources.json not generated"; exit 1; }
[ -f "$BRAIN_PATH/.brain/index/search.jsonl" ] || { echo "FAILED: search.jsonl not generated"; exit 1; }
[ -f "$BRAIN_PATH/.brain/index/manifest.json" ] || { echo "FAILED: manifest.json not generated"; exit 1; }
brain-index status | grep -q "health: ok" || { echo "FAILED: brain-index status not ok"; exit 1; }
brain-index page search-topic | grep -q "Search Topic" || { echo "FAILED: brain-index page failed"; exit 1; }
brain-index backlinks decision-search | grep -q "search-topic" || { echo "FAILED: brain-index backlinks failed"; exit 1; }
brain-index sources raw/demo-source.md | grep -q "decision-search" || { echo "FAILED: brain-index sources failed"; exit 1; }
brain-search rarebrainterm | grep -q "wiki/search-topic.md" || { echo "FAILED: brain-search did not find search-topic"; exit 1; }
brain-search rarebrainterm --type concept | grep -q "wiki/search-topic.md" || { echo "FAILED: brain-search type filter failed"; exit 1; }
brain-index stale | grep -q "status: ok" || { echo "FAILED: brain-index stale should be ok after rebuild"; exit 1; }

echo "--- wiki stale check ---"
cat >> "$BRAIN_PATH/wiki/search-topic.md" <<EOF

New stale marker.
EOF
set +e
brain-index stale > /tmp/brain_index_stale.log 2>&1
stale_exit=$?
set -e
[ "$stale_exit" -ne 0 ] || { echo "FAILED: brain-index stale should fail after wiki change"; exit 1; }
grep -q "wiki/search-topic.md" /tmp/brain_index_stale.log || { echo "FAILED: stale wiki file not reported"; exit 1; }

echo "--- raw stale check ---"
brain-index rebuild > /dev/null
cat >> "$BRAIN_PATH/raw/demo-source.md" <<EOF

Stale raw.
EOF
set +e
brain-index stale > /tmp/brain_index_stale_raw.log 2>&1
stale_exit=$?
set -e
[ "$stale_exit" -ne 0 ] || { echo "FAILED: brain-index stale should fail after raw change"; exit 1; }
grep -q "raw/demo-source.md" /tmp/brain_index_stale_raw.log || { echo "FAILED: stale raw file not reported"; exit 1; }

echo "--- tasks stale check ---"
brain-index rebuild > /dev/null
cat >> "$BRAIN_PATH/tasks/active.md" <<EOF

# Stale tasks.
EOF
set +e
brain-index stale > /tmp/brain_index_stale_tasks.log 2>&1
stale_exit=$?
set -e
[ "$stale_exit" -ne 0 ] || { echo "FAILED: brain-index stale should fail after tasks change"; exit 1; }
grep -q "tasks/active.md" /tmp/brain_index_stale_tasks.log || { echo "FAILED: stale tasks file not reported"; exit 1; }

brain-index rebuild --with-obsidian > /dev/null
[ -f "$BRAIN_PATH/wiki/_views/brain-pages.base" ] || { echo "FAILED: brain-pages.base not exported"; exit 1; }
[ -f "$BRAIN_PATH/wiki/_views/brain-sources.base" ] || { echo "FAILED: brain-sources.base not exported"; exit 1; }
[ -f "$BRAIN_PATH/wiki/_views/brain-decisions.base" ] || { echo "FAILED: brain-decisions.base not exported"; exit 1; }
[ -f "$BRAIN_PATH/wiki/_views/brain-tasks.base" ] || { echo "FAILED: brain-tasks.base not exported"; exit 1; }
[ -f "$BRAIN_PATH/wiki/_views/link-graph.canvas" ] || { echo "FAILED: link-graph.canvas not exported"; exit 1; }
python3 -m json.tool "$BRAIN_PATH/wiki/_views/link-graph.canvas" > /dev/null || { echo "FAILED: link-graph.canvas invalid JSON"; exit 1; }
