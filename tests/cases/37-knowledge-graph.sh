#!/usr/bin/env bash
# case: knowledge-graph
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying knowledge graph extraction"

cat <<'EOF' > "$BRAIN_PATH/wiki/test-node.md"
---
title: Test Node
implements: [some-other-node]
depends_on: [yet-another-node]
refutes: [bad-idea]
---
# Test

Links to [[some-inline-link]]
EOF

cat <<'EOF' > "$BRAIN_PATH/wiki/test-canvas.canvas"
{
  "nodes": [
    {"id": "node1", "type": "text", "text": "Canvas text node"},
    {"id": "node2", "type": "file", "file": "wiki/test-node.md"}
  ],
  "edges": [
    {"id": "edge1", "fromNode": "node1", "toNode": "node2", "label": "canvas-edge-label"}
  ]
}
EOF

brain-index rebuild >/dev/null

GRAPH_FILE="$BRAIN_PATH/.brain/index/graph.json"
if [ ! -f "$GRAPH_FILE" ]; then
  echo "FAILED: graph.json was not created"
  exit 1
fi

# Check if wiki nodes are extracted
grep -q '"id": "test-node"' "$GRAPH_FILE" || {
  echo "FAILED: wiki node missing from graph.json"
  exit 1
}

# Check if implements edge is extracted
grep -q '"type": "implements"' "$GRAPH_FILE" || {
  echo "FAILED: implements edge missing from graph.json"
  exit 1
}

# Check if task nodes are extracted
grep -q '"type": "task"' "$GRAPH_FILE" || {
  echo "FAILED: task node missing from graph.json"
  exit 1
}

# Check if canvas nodes are extracted
grep -q '"id": "node1"' "$GRAPH_FILE" || {
  echo "FAILED: canvas node missing from graph.json"
  exit 1
}

# Check if canvas edges are extracted
grep -q '"type": "canvas-edge-label"' "$GRAPH_FILE" || {
  echo "FAILED: canvas edge missing from graph.json"
  exit 1
}

echo "knowledge-graph OK"
