#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-vector fallback (no deps)"
brain-vector support > /tmp/brain_vector_support.txt
grep -q "ChromaDB" /tmp/brain_vector_support.txt || { echo "FAILED: support matrix missing ChromaDB"; exit 1; }
grep -q "BM25" /tmp/brain_vector_support.txt || { echo "FAILED: support matrix missing BM25 fallback"; exit 1; }
grep -q "brain-vector setup" /tmp/brain_vector_support.txt || { echo "FAILED: support matrix missing setup command"; exit 1; }
brain-vector support --json > /tmp/brain_vector_support.json
python3 - <<'PYEOF'
import json
from pathlib import Path
data = json.loads(Path("/tmp/brain_vector_support.json").read_text())
assert data["primary"]["backend"] == "chromadb", data
assert data["primary"]["status"] == "optional", data
assert "brain-vector index" in data["primary"]["commands"], data
assert "brain-vector setup [--yes]" in data["primary"]["commands"], data
assert data["fallback"]["backend"] == "BM25", data
assert data["fallback"]["status"] == "required", data
PYEOF
setup_out=$(brain-vector setup 2>&1)
echo "$setup_out" | grep -q "did not install anything" || { echo "FAILED: setup without --yes must be non-installing: $setup_out"; exit 1; }
echo "$setup_out" | grep -q "brain-vector setup --yes" || { echo "FAILED: setup without --yes missing opt-in hint: $setup_out"; exit 1; }
# brain-vector must exit 1 and print the install hint when chromadb is missing
if python3 -c "import chromadb" 2>/dev/null; then
  echo "brain-vector: chromadb present — skipping fallback test"
else
  set +e
  out=$(brain-vector status 2>&1); rc=$?
  out2=$(brain-vector search "test" 2>&1); rc2=$?
  out3=$(brain-vector index rebuild 2>&1); rc3=$?
  set -e
  [ $rc -ne 0 ] || { echo "FAILED: brain-vector status should exit 1 without deps"; exit 1; }
  echo "$out" | grep -q "pip install chromadb" || { echo "FAILED: brain-vector missing pip hint: $out"; exit 1; }
  echo "$out" | grep -q "brain-search" || { echo "FAILED: brain-vector missing fallback hint: $out"; exit 1; }
  [ $rc2 -ne 0 ] || { echo "FAILED: brain-vector search should exit 1 without deps"; exit 1; }
  [ $rc3 -ne 0 ] || { echo "FAILED: brain-vector index rebuild should exit 1 without deps"; exit 1; }
  echo "brain-vector fallback OK (deps absent, correct exit 1 + hint)"
fi
