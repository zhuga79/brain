import os
import json
import time
import subprocess
from pathlib import Path
from common import mcp, BRAIN, ACTIVE, DONE, LOCKS, find_blocks, parse_block

def _run_brain_vector(args: list[str]) -> dict:
    """Run brain-vector CLI and return structured result."""
    cmd = ["brain-vector"] + args
    result = subprocess.run(cmd, capture_output=True, text=True,
                            env={**os.environ, "BRAIN_PATH": str(BRAIN)})
    return {
        "ok": result.returncode == 0,
        "output": result.stdout.strip(),
        "error": result.stderr.strip() if result.returncode != 0 else "",
    }

def _collect_dashboard_status() -> dict:
    """Collect brain status inline."""
    tasks_active = []
    tasks_done_count = 0
    if ACTIVE.exists():
        for blk in find_blocks(ACTIVE.read_text()):
            info = parse_block(blk)
            if info: tasks_active.append(info)
    if DONE.exists():
        tasks_done_count = len(find_blocks(DONE.read_text()))

    open_count = sum(1 for t in tasks_active if t["state"] == " ")
    in_progress_count = sum(1 for t in tasks_active if t["state"] == "~")
    blocked_count = sum(1 for t in tasks_active if t["state"] == "!")

    locks_items = []
    stale_count = 0
    now_ts = int(time.time())
    if LOCKS.exists():
        for lock_dir in LOCKS.iterdir():
            if lock_dir.is_dir():
                owner_file = lock_dir / "owner"
                if owner_file.exists():
                    try:
                        content = owner_file.read_text().strip()
                        parts = content.split("|")
                        if len(parts) >= 3:
                            agent = parts[0]; epoch = int(parts[1]); ttl = int(parts[2])
                            age = now_ts - epoch; stale = age > ttl
                            if stale: stale_count += 1
                            locks_items.append({"task_id": lock_dir.name, "owner": agent,
                                                "age_seconds": age, "ttl_seconds": ttl, "stale": stale})
                    except Exception: pass

    council_items = []
    council_dir = BRAIN / "council"
    if council_dir.exists():
        for task_dir in council_dir.iterdir():
            if task_dir.is_dir():
                opinions = [f.stem for f in task_dir.iterdir() if f.is_file() and f.stem != "synthesis"]
                council_items.append({"task_id": task_dir.name, "opinions": opinions,
                                      "has_synthesis": (task_dir / "synthesis.md").exists()})

    index_path = BRAIN / ".brain" / "index" / "pages.json"
    index_count = 0
    if index_path.exists():
        try: index_count = len(json.loads(index_path.read_text()))
        except Exception: pass

    return {
        "brain": str(BRAIN),
        "tasks": {"summary": {"open": open_count, "in_progress": in_progress_count, "blocked": blocked_count, "done": tasks_done_count},
                  "active": tasks_active, "done_count": tasks_done_count},
        "locks": {"count": len(locks_items), "stale_count": stale_count, "items": locks_items},
        "council": {"count": len(council_items), "items": council_items},
        "index": {"page_count": index_count},
    }

@mcp.tool()
def dashboard_status() -> dict:
    """Return full brain status (tasks, locks, council, index) as JSON."""
    return _collect_dashboard_status()

@mcp.tool()
def dashboard_export(out_path: str = "") -> dict:
    """Export brain dashboard HTML."""
    candidates = [Path.home() / ".local" / "bin" / "brain-dashboard",
                  Path(__file__).resolve().parent.parent / "bin" / "brain-dashboard",
                  "brain-dashboard"]
    bin_path = "brain-dashboard"
    for c in candidates:
        if isinstance(c, Path) and c.exists():
            bin_path = str(c); break
    cmd = [bin_path, "export"]
    if out_path: cmd.extend(["--out", out_path])
    env = os.environ.copy(); env["BRAIN_PATH"] = str(BRAIN)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr.strip() or result.stdout.strip()}
    out = result.stdout.strip(); path = ""
    if "Dashboard exported: " in out: path = out.split("Dashboard exported: ")[-1].strip()
    elif "Exported to " in out: path = out.split("Exported to ")[-1].strip()
    return {"ok": True, "path": path, "message": out}

@mcp.tool()
def list_doctrines() -> dict:
    """List all doctrine files."""
    doctrine_dir = BRAIN / "doctrine"
    if not doctrine_dir.exists(): return {"doctrines": [], "count": 0}
    items = []
    for f in sorted(doctrine_dir.glob("*.md")):
        items.append({"slug": f.stem, "file": str(f)})
    return {"doctrines": items, "count": len(items)}

@mcp.tool()
def search_doctrines(query: str) -> dict:
    """Case-insensitive search across all doctrine files."""
    doctrine_dir = BRAIN / "doctrine"
    if not doctrine_dir.exists(): return {"results": [], "count": 0}
    results = []; q = query.lower()
    for f in sorted(doctrine_dir.glob("*.md")):
        content = f.read_text()
        if q in content.lower():
            lines = [ln for ln in content.splitlines() if q in ln.lower()]
            results.append({"slug": f.stem, "matches": lines[:5]})
    return {"results": results, "count": len(results)}
