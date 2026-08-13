import os
import re
import json
import sys
import time
import shutil
from datetime import datetime, timezone
import subprocess
from pathlib import Path
from typing import Optional, Any

import brain_tasks
import brain_task_parser
import brain_wiki
import brain_index

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from fastmcp import FastMCP  # fallback

BRAIN = Path(os.environ.get("BRAIN_PATH", str(Path.home() / "brain")))
ACTIVE = BRAIN / "tasks" / "active.md"
DONE = BRAIN / "tasks" / "done.md"
LOG = BRAIN / "wiki" / "log.md"
INDEX = BRAIN / "wiki" / "index.md"
LOCKS = BRAIN / ".locks"
PRD_DIR = BRAIN / "prd"
TEAMS = BRAIN / "teams"

mcp = FastMCP("brain")

# -------- helpers --------

def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def append_log(op: str, task_id: str = "", agent: str = "", message: str = ""):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if not LOG.exists():
        LOG.write_text("# Log\n\n")
    with LOG.open("a") as f:
        f.write(f"## [{ts()}] {op} | {task_id} | {agent} | {message}\n")

def git_commit(msg: str):
    """Auto-commit if BRAIN is a git repo."""
    if not (BRAIN / ".git").exists():
        return
    try:
        add = subprocess.run(
            ["git", "-C", str(BRAIN), "add",
             "tasks/", "wiki/", "council/", "raw/", "doctrine/",
             "prd/", "roles/", "teams/", "MEMORY.md"],
            check=False, capture_output=True, text=True,
        )
        if add.returncode != 0 and add.stderr.strip():
            sys.stderr.write(f"warning: git add failed: {add.stderr.strip()[:200]}\n")
            return
        commit = subprocess.run(
            ["git", "-C", str(BRAIN), "commit", "-m", msg, "--quiet"],
            check=False, capture_output=True, text=True,
        )
        if commit.returncode != 0:
            err = (commit.stderr.strip() or commit.stdout.strip())[:200]
            if "nothing to commit" not in err.lower():
                sys.stderr.write(f"warning: git commit failed: {err}\n")
    except Exception as e:
        sys.stderr.write(f"warning: git_commit raised: {e}\n")

def parse_block(block: str) -> dict:
    """Распарсить markdown-блок задачи в dict (делегировано brain_task_parser)."""
    return brain_task_parser.parse_block(block)

def find_blocks(text: str) -> list[str]:
    return brain_task_parser.find_blocks(text)

def is_done(tid: str) -> bool:
    """Задача [x] либо в active.md либо в done.md."""
    combined = ""
    if ACTIVE.exists():
        combined += ACTIVE.read_text()
    if DONE.exists():
        combined += "\n" + DONE.read_text()
    return brain_task_parser.is_done(combined, tid)

def find_task_block(tid: str) -> Optional[str]:
    if ACTIVE.exists():
        if m := brain_task_parser.find_block(ACTIVE.read_text(), tid):
            return m
    if DONE.exists():
        if m := brain_task_parser.find_block(DONE.read_text(), tid):
            return m
    return None

def expand_council(items: list[str]) -> list[str]:
    """Развернуть team:<name> в список ролей."""
    out = []
    for item in items:
        item = item.strip()
        if item.startswith("team:"):
            tname = item[5:]
            tfile = BRAIN / "teams" / f"{tname}.md"
            if tfile.exists():
                if m := re.search(r"^roles:\s*\[([^\]]*)\]", tfile.read_text(), re.M):
                    out.extend([r.strip() for r in m.group(1).split(",") if r.strip()])
        else:
            out.append(item)
    seen = set()
    return [r for r in out if not (r in seen or seen.add(r))]
