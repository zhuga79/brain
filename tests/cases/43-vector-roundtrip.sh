#!/usr/bin/env bash
# Verifies vector search layer and hybrid search integration.
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-vector roundtrip and hybrid search"

BRAIN_PATH="${BRAIN_PATH:-$HOME/brain}"
export BRAIN_PATH

# Check if optional vector deps are available (including vendor dir)
_CHECK_CMD="import sys, os; from pathlib import Path; b=Path(os.environ.get('BRAIN_PATH', '')); v=b/'.brain'/'vector'/'vendor'; [sys.path.insert(0, str(v)) if v.exists() else None]; import chromadb, sentence_transformers"
if ! python3 -c "$_CHECK_CMD" 2>/dev/null; then
  echo "SKIP: chromadb or sentence_transformers not installed (checked in $BRAIN_PATH/.brain/vector/vendor)"
  exit 0
fi

# 1. Ensure BM25 index is ready (prerequisite for vector index)
echo "--- building machine index (BM25) ---"
brain-index rebuild > /dev/null

# 2. Build vector index
echo "--- building vector index ---"
# We use rebuild to ensure a clean state
brain-vector index rebuild > /tmp/brain_vector_index.log
grep -q "OK: vector index built" /tmp/brain_vector_index.log || { 
  echo "FAILED: vector index build failed"
  cat /tmp/brain_vector_index.log
  exit 1 
}

# 3. Test vector search CLI
echo "--- vector search (direct) ---"
brain-vector search "phase 19" --top-k 2 --json > /tmp/vsearch.json
python3 -c 'import json, sys; d=json.load(open("/tmp/vsearch.json")); sys.exit(0 if d.get("ok") and len(d.get("results", [])) > 0 else 1)' || { 
  echo "FAILED: vector search json invalid or empty"
  cat /tmp/vsearch.json
  exit 1 
}

# 4. Test brain-search --mode vector
echo "--- brain-search --mode vector ---"
brain-search "phase 19" --mode vector --json > /tmp/bs_vector.json
python3 -c 'import json, sys; d=json.load(open("/tmp/bs_vector.json")); sys.exit(0 if d.get("mode") == "vector" and len(d.get("results", [])) > 0 else 1)' || { 
  echo "FAILED: brain-search --mode vector failed"
  cat /tmp/bs_vector.json
  exit 1 
}

# 5. Test brain-search --mode hybrid
echo "--- brain-search --mode hybrid ---"
brain-search "phase 19" --mode hybrid --json > /tmp/bs_hybrid.json
python3 -c 'import json, sys; d=json.load(open("/tmp/bs_hybrid.json")); sys.exit(0 if d.get("mode") == "hybrid" and len(d.get("results", [])) > 0 else 1)' || { 
  echo "FAILED: brain-search --mode hybrid failed"
  cat /tmp/bs_hybrid.json
  exit 1 
}

# Verify hybrid score label in text output
echo "--- brain-search text output (hybrid) ---"
brain-search "phase 19" --mode hybrid > /tmp/bs_hybrid.txt
grep -q "(hybrid)" /tmp/bs_hybrid.txt || { 
  echo "FAILED: hybrid label missing in text output"
  cat /tmp/bs_hybrid.txt
  exit 1 
}

# 6. Verify vector status
echo "--- vector status ---"
brain-vector status > /tmp/bv_status.txt
grep -q "vector index: present" /tmp/bv_status.txt || { 
  echo "FAILED: brain-vector status incorrect"
  cat /tmp/bv_status.txt
  exit 1 
}

echo "OK: vector roundtrip and hybrid search verified"
