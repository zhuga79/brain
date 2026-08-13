#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> [Python] Starting functional smoke test for server.py"
TMP_PYTHON_BRAIN=$(mktemp -d)
(
    export BRAIN_PATH="$TMP_PYTHON_BRAIN"
    export SERVER_PY="$PROJECT_ROOT/runtime/mcp/server.py"
    python3 <<EOF
import sys
import os
import re
import time
from pathlib import Path
from types import ModuleType

# 1. Mock MCP environment to avoid network/dependency issues
mcp_mod = ModuleType("mcp")
mcp_mod.server = ModuleType("mcp.server")
mcp_mod.server.fastmcp = ModuleType("mcp.server.fastmcp")

class FakeMCP:
    def __init__(self, name): self.name = name
    def tool(self): return lambda f: f
    def run(self): pass

mcp_mod.server.fastmcp.FastMCP = FakeMCP
sys.modules["mcp"] = mcp_mod
sys.modules["mcp.server"] = mcp_mod.server
sys.modules["mcp.server.fastmcp"] = mcp_mod.server.fastmcp
sys.modules["fastmcp"] = mcp_mod.server.fastmcp

# 2. Import server.py after setting BRAIN_PATH
import importlib.util
spec = importlib.util.spec_from_file_location("server", os.environ["SERVER_PY"])
server = importlib.util.module_from_spec(spec)
sys.modules["server"] = server
spec.loader.exec_module(server)

# 3. Setup test environment
brain = Path(os.environ["BRAIN_PATH"])
(brain / "prd").mkdir(parents=True, exist_ok=True)
(brain / "tasks").mkdir(parents=True, exist_ok=True)
(brain / "wiki").mkdir(parents=True, exist_ok=True)
(brain / "prd" / "_TEMPLATE.md").write_text("status: draft\n\n# <Title>\n\ntask: <task-id>\ncreated: <ts>\n\n## Subtasks\n")

# 4. Functional Tests

print(">>> [Python] Verifying init_prd")
(brain / "tasks" / "active.md").write_text("- [ ] [P1] t-prd — PRD Task\n")
res = server.init_prd("t-prd")
assert res.get("status") == "ok", f"init_prd failed: {res}"
prd_file = brain / "prd" / "t-prd.md"
assert prd_file.exists(), "PRD file not created"
assert "PRD Task" in prd_file.read_text(), "Title not replaced"

print(">>> [Python] Verifying commit_prd")
with prd_file.open("a") as f:
    f.write("- [ ] [P1] s1 — Sub 1\n      role: developer\n- [ ] [P2] s2 — Sub 2\n      role: developer\n      depends_on: [s1]\n")

res = server.commit_prd("t-prd")
assert res.get("status") == "ok", f"commit_prd failed: {res}"
active_text = (brain / "tasks" / "active.md").read_text()
assert "t-prd-s1" in active_text, "Subtask 1 missing"
assert "t-prd-s2" in active_text, "Subtask 2 missing"
assert "parent: t-prd" in active_text, "Parent field missing"
assert "depends_on: [t-prd-s1]" in active_text, "Dependency not normalized"

print(">>> [Python] Verifying get_prd_status")
res = server.get_prd_status("t-prd")
assert res.get("total") == 2, f"Expected 2 subtasks, got {res.get('total')} in {res}"
assert res.get("done") == 0, f"Expected 0 done, got {res.get('done')} in {res}"

print(">>> [Python] Verifying get_next_task exact matching")
# Case: t-dep depends on t-par. t-par-child is done.
(brain / "tasks" / "active.md").write_text("# Active tasks\n\n- [ ] [P1] t-dep — Dependent\n      role: developer\n      depends_on: [t-par]\n")
(brain / "tasks" / "done.md").write_text("# Done tasks\n\n- [x] [P1] t-par-child — Child Done\n      completed: 2026-05-02T00:00:00Z\n")

res = server.get_next_task(role="developer")
assert res["task"] is None, "Should be blocked by t-par (exact match fail)"

# Mark t-par as done
with (brain / "tasks" / "done.md").open("a") as f:
    f.write("\n- [x] [P1] t-par — Parent Done\n      completed: 2026-05-02T00:00:00Z\n")

res = server.get_next_task(role="developer")
assert res["task"] is not None and res["task"]["id"] == "t-dep", "Should be available now"

print(">>> [Python] Verifying wiki/raw MCP tools")
res = server.ingest_source("mcp-source", "MCP source body", title="MCP Source", url="https://example.com/mcp")
assert res.get("status") == "ok", f"ingest_source failed: {res}"
assert (brain / "raw" / "mcp-source.md").exists(), "MCP raw source missing"
assert (brain / "wiki" / "source-mcp-source.md").exists(), "MCP source-summary missing"

res = server.add_raw_source("mcp-source", "duplicate", title="MCP Source")
assert res.get("error") and "already exists" in res["error"], f"duplicate raw was not rejected: {res}"

res = server.write_wiki_page("manual-page", "# Manual\n\nHuman content.", curation="human", protected=True)
assert res.get("status") == "ok", f"manual page write failed: {res}"
res = server.write_wiki_page("manual-page", "# Manual\n\nAgent overwrite.", curation="agent")
assert res.get("error") and "protected" in res["error"], f"protected page overwrite should fail: {res}"

res = server.write_wiki_page("regular-page", "# Regular\n\nVersion 1.", curation="agent")
assert res.get("status") == "ok", f"regular page write failed: {res}"
fm1, _ = server.brain_wiki.parse_frontmatter((brain / "wiki" / "regular-page.md").read_text())
res = server.write_wiki_page("regular-page", "# Regular\n\nVersion 2.", curation="agent")
assert res.get("status") == "ok", f"regular page rewrite failed: {res}"
fm2, _ = server.brain_wiki.parse_frontmatter((brain / "wiki" / "regular-page.md").read_text())
assert fm1["created"] == fm2["created"], "created date was not preserved"

res = server.regenerate_wiki_index()
assert res.get("status") == "ok", f"regenerate_wiki_index failed: {res}"
assert "[[source-mcp-source]]" in (brain / "wiki" / "index.md").read_text(), "MCP index missing source page"

res = server.validate_wiki()
assert res.get("status") == "ok", f"validate_wiki failed: {res}"
res = server.lint_wiki(fix_index=True)
assert res.get("status") == "ok", f"lint_wiki failed: {res}"

print(">>> [Python] Verifying index/search MCP tools")
(brain / "wiki" / "mcp-index-topic.md").write_text("""---
title: MCP Index Topic
type: concept
created: 2026-05-02
updated: 2026-05-02
curation: agent
protected: false
source_policy: advisory
tags: []
sources: [raw/mcp-source.md]
related: []
---

# MCP Index Topic

Contains raremcpterm and links to [[regular-page]].
""")
res = server.rebuild_index()
assert res.get("status") == "ok", f"rebuild_index failed: {res}"
res = server.index_status()
assert res.get("status") == "ok", f"index_status failed: {res}"
res = server.search_brain("raremcpterm", limit=5)
assert res.get("count", 0) >= 1, f"search_brain found no results: {res}"
assert any(item["path"] == "wiki/mcp-index-topic.md" for item in res["results"]), f"search result missing mcp-index-topic: {res}"
res = server.get_backlinks("regular-page")
assert "mcp-index-topic" in res.get("backlinks", []), f"backlinks missing mcp-index-topic: {res}"
res = server.get_source_map("raw/mcp-source.md")
assert "mcp-index-topic" in res.get("source_map", {}).get("pages", []), f"source map missing mcp-index-topic: {res}"

print(">>> [Python] Verifying dashboard_status locks (new format)")
lock_dir = brain / ".locks" / "t-lock-test"
lock_dir.mkdir(parents=True, exist_ok=True)
# agent|epoch|ttl
now_ts = int(time.time())
(lock_dir / "owner").write_text(f"test-agent|{now_ts - 100}|600")

res = server.dashboard_status()
lock_item = next((i for i in res["locks"]["items"] if i["task_id"] == "t-lock-test"), None)
assert lock_item, "Lock item not found in dashboard_status"
assert lock_item["owner"] == "test-agent", f"Wrong owner: {lock_item.get('owner')}"
assert lock_item["age_seconds"] >= 100, f"Wrong age: {lock_item.get('age_seconds')}"
assert lock_item["ttl_seconds"] == 600, f"Wrong ttl: {lock_item.get('ttl_seconds')}"
assert lock_item["stale"] is False, "Lock should not be stale"

stale_dir = brain / ".locks" / "t-stale-test"
stale_dir.mkdir(parents=True, exist_ok=True)
(stale_dir / "owner").write_text(f"stale-agent|{now_ts - 1000}|600")
res = server.dashboard_status()
stale_item = next((i for i in res["locks"]["items"] if i["task_id"] == "t-stale-test"), None)
assert stale_item, "Stale lock item not found"
assert stale_item["stale"] is True, "Lock should be stale"

print(">>> [Python] Verifying doctrine MCP tools")
(brain / "doctrine").mkdir(parents=True, exist_ok=True)
(brain / "doctrine" / "mcp-test-doc.md").write_text("MCP Test doctrine content with unique-key-word.")
res = server.list_doctrines()
assert any(d["slug"] == "mcp-test-doc" for d in res["doctrines"]), "mcp-test-doc missing from list"
res = server.search_doctrines("unique-key-word")
assert any(r["slug"] == "mcp-test-doc" for r in res["results"]), "mcp-test-doc missing from search"
res = server.get_doctrine(name="mcp-test-doc")
assert "unique-key-word" in res.get("content", ""), "get_doctrine content missing"

print(">>> [Python] Verifying dashboard_export path parsing")
# We need brain-dashboard to be available or mocked.
# Since this is a smoke test that installs it, we can try to use it if it exists.
# But for the Python-only part, we can mock subprocess.run.
import subprocess
orig_run = subprocess.run
def mock_run(cmd, **kwargs):
    if cmd[0].endswith("brain-dashboard") and "export" in cmd:
        class MockRes:
            returncode = 0
            stdout = "Dashboard exported: /tmp/brain-dash.html\n"
            stderr = ""
        return MockRes()
    return orig_run(cmd, **kwargs)
server.subprocess.run = mock_run
res = server.dashboard_export()
assert res.get("ok") is True, f"dashboard_export failed: {res}"
assert res.get("path") == "/tmp/brain-dash.html", f"Wrong path: {res.get('path')}"
server.subprocess.run = orig_run

print(">>> [Python] Verifying get_task_bundle")
(brain / "tasks" / "active.md").write_text(
    "# Active\n\n- [ ] [P1] t-bundle-test — Bundle test task\n      role: developer\n"
)
res = server.get_task_bundle("t-bundle-test")
assert res["task"]["state"] == "open", f"Expected open task: {res['task']}"
assert res["lock"]["held"] is False, f"Expected no lock: {res['lock']}"
assert res["council"]["exists"] is False, f"Expected no council: {res['council']}"
assert "health" in res["index"], f"Expected index health: {res['index']}"
res_missing = server.get_task_bundle("t-nonexistent")
assert res_missing["task"]["state"] == "not_found", f"Expected not_found: {res_missing['task']}"
print("get_task_bundle OK")

print(">>> [Python] Verifying vector MCP tools (fallback mode)")
# vector_status and vector_search must exist and return structured dicts
# They delegate to brain-vector CLI which exits 1 without chromadb
import subprocess as _sp, os as _os
orig_run2 = _sp.run
def mock_vector_run(cmd, **kwargs):
    # Simulate brain-vector returning dependency missing error
    class MockRes:
        returncode = 1
        stdout = ""
        stderr = "brain-vector: dependency missing — install chromadb and sentence-transformers:\n  pip install chromadb sentence-transformers\nFallback: use brain-search (BM25) instead."
    return MockRes()
server.subprocess.run = mock_vector_run
vs = server.vector_status()
assert isinstance(vs, dict), f"vector_status must return dict: {vs}"
assert "ok" in vs, f"vector_status missing 'ok': {vs}"
assert vs["ok"] is False, f"vector_status should be ok=False without deps: {vs}"
assert "error" in vs or "output" in vs, f"vector_status missing error/output: {vs}"
vsr = server.vector_search(query="brain memory", top_k=3)
assert isinstance(vsr, dict), f"vector_search must return dict: {vsr}"
assert "ok" in vsr, f"vector_search missing 'ok': {vsr}"
assert vsr["ok"] is False, f"vector_search should be ok=False without deps: {vsr}"
server.subprocess.run = orig_run2
print("vector MCP tools OK")

print(">>> [Python] MCP functional smoke passed")
EOF
)
rm -rf "$TMP_PYTHON_BRAIN"
