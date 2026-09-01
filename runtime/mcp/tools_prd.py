import re
from brain_core import prdfile
from common import mcp, BRAIN, ACTIVE, DONE, LOG, PRD_DIR, append_log, git_commit, ts, find_task_block, parse_block, find_blocks
from result import ok, error

@mcp.tool()
def init_prd(task_id: str) -> dict:
    """Initialize a PRD document from template.
    Refuses if PRD already exists."""
    PRD_DIR.mkdir(parents=True, exist_ok=True)
    f = PRD_DIR / f"{task_id}.md"
    if f.exists():
        return error(f"PRD {task_id}.md already exists")
    
    template_file = PRD_DIR / "_TEMPLATE.md"
    if not template_file.exists():
        return error("_TEMPLATE.md not found in prd/")
    
    # Extract title from active.md
    title = "TODO"
    block = find_task_block(task_id)
    if block:
        info = parse_block(block)
        if info.get("title"):
            title = info["title"]
    
    content = template_file.read_text()
    content = content.replace("<task-id>", task_id)
    content = content.replace("<ts>", ts())
    content = content.replace("<Title>", title)
    
    f.write_text(content)
    append_log("prd-init", task_id)
    git_commit(f"prd-init: {task_id}")
    return ok(path=str(f.relative_to(BRAIN)))

@mcp.tool()
def commit_prd(task_id: str) -> dict:
    """Parse Subtasks from PRD and append to active.md.
    Normalizes local IDs and rewrites depends_on."""
    f = PRD_DIR / f"{task_id}.md"
    if not f.exists():
        return error(f"no PRD at {f}")

    try:
        # The prd-commit audit line is written inside the queue transaction by
        # prdfile.commit — queue state and its record can no longer diverge on
        # a crash or a concurrent commit.
        result = prdfile.commit(f, ACTIVE, DONE, task_id, log_path=LOG)
    except prdfile.PRDError as exc:
        return error(str(exc))

    git_commit(f"prd-commit: {task_id}")

    return ok(
        parent_id=task_id,
        subtasks_count=len(result.subtasks),
        appended_count=len(result.appended_ids),
        recovered=result.recovered,
        subtasks=[{"prio": item.prio, "id": item.task_id, "title": item.title} for item in result.subtasks],
    )

@mcp.tool()
def get_prd_status(task_id: str) -> dict:
    """Status of a PRD: all subtasks with their state."""
    f = BRAIN / "prd" / f"{task_id}.md"
    if not f.exists():
        return error("no PRD for this task")
    text = f.read_text()
    status = "draft"
    if m := re.search(r"^status:\s*(\S+)", text, re.M):
        status = m.group(1)
    combined = ACTIVE.read_text() + "\n" + (DONE.read_text() if DONE.exists() else "")
    subtasks = []
    for block in find_blocks(combined):
        if f"parent: {task_id}" in block:
            info = parse_block(block)
            if info:
                subtasks.append({k: v for k, v in info.items() if k != "raw"})
    return {"prd_status": status, "subtasks": subtasks,
            "total": len(subtasks),
            "done": sum(1 for s in subtasks if s.get("state") == "x")}

@mcp.tool()
def read_prd(task_id: str) -> dict:
    """Read the full PRD document for a task."""
    f = BRAIN / "prd" / f"{task_id}.md"
    if not f.exists():
        return error("no PRD")
    return {"content": f.read_text()}
