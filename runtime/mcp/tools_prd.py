import re
from common import mcp, BRAIN, ACTIVE, DONE, PRD_DIR, append_log, git_commit, ts, find_task_block, parse_block, find_blocks
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
    
    prd_text = f.read_text()
    if re.search(r"^status:\s*committed", prd_text, re.M):
        return error("already committed")

    # Find Subtasks section
    m = re.search(r"^## Subtasks\s*$(.+?)(?=^## |\Z)", prd_text, re.S | re.M)
    if not m:
        return error("no ## Subtasks section in PRD")
    sub_text = m.group(1)

    # Find subtask blocks
    blocks = re.findall(r"(- \[ \] \[P[012]\][^\n]+(?:\n      [^\n]*)*)", sub_text)
    if not blocks:
        return error("no subtasks found")

    normalized = []
    local_to_full = {}

    for b in blocks:
        head_match = re.match(r"- \[ \] \[(P[012])\] (\S+) — (.+)", b)
        if not head_match:
            continue
        prio, local_id, rest = head_match.groups()
        full_id = local_id if local_id.startswith("t-") else f"{task_id}-{local_id}"
        local_to_full[local_id] = full_id
        normalized.append((prio, full_id, rest, b))

    out_blocks = []
    for prio, full_id, title, original in normalized:
        body_lines = original.split("\n")[1:]
        new_body = []
        for line in body_lines:
            line2 = re.sub(
                r"depends_on: *\[([^\]]*)\]",
                lambda mm: "depends_on: [" + ", ".join(
                    local_to_full.get(d.strip(), d.strip())
                    for d in mm.group(1).split(",") if d.strip()
                ) + "]",
                line,
            )
            new_body.append(line2)

        if not any("parent:" in l for l in new_body):
            new_body.insert(0, f"      parent: {task_id}")

        block_out = f"- [ ] [{prio}] {full_id} — {title}\n" + "\n".join(new_body)
        out_blocks.append(block_out)

    # Append to active.md
    active_text = ACTIVE.read_text() if ACTIVE.exists() else "# Active tasks\n"
    header = f"\n## PRD subtasks of {task_id}\n"
    new_active = active_text.rstrip() + "\n" + header + "\n" + "\n\n".join(out_blocks) + "\n"
    ACTIVE.write_text(new_active)

    # Update PRD status
    new_prd = re.sub(r"^status: draft\s*$", "status: committed", prd_text, count=1, flags=re.M)
    f.write_text(new_prd)

    append_log("prd-commit", task_id, "", f"{len(normalized)} subtasks")
    git_commit(f"prd-commit: {task_id}")

    return ok(
        parent_id=task_id,
        subtasks_count=len(normalized),
        subtasks=[{"prio": p, "id": i, "title": t.split("\n")[0]} for p, i, t, _ in normalized],
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
