"""MCP-инструменты очереди — тонкий слой над brain_app.queue.

Здесь была вторая независимая реализация контракта очереди: свои фильтры,
свой генератор идентификатора и запись в `active.md` через `open("a")` и
`write_text` — мимо блокировки, которую уже брал `brain-task`. Инструмент,
вызванный из редактора в момент работы агента, затирал чужую правку.
"""

from typing import Optional

from brain_app import queue
from common import BRAIN, append_log, git_commit, mcp
from result import error, ok


@mcp.tool()
def list_tasks(role: str = "", mode: str = "", status: str = "open") -> dict:
    """List tasks in active.md.

    Args:
        role: filter by role (empty = all)
        mode: filter by mode: solo / council / prd (empty = all)
        status: open / in_progress / blocked / all
    """
    tasks = queue.filter_tasks(queue.blocks(BRAIN), role=role, mode=mode, status=status)
    return {"tasks": [{k: v for k, v in task.items() if k != "raw"} for task in tasks], "total": len(tasks)}


@mcp.tool()
def get_task(task_id: str) -> dict:
    """Get full task block by id."""
    info, raw = queue.find(task_id, BRAIN)
    if not info:
        return error(f"task {task_id} not found")
    return {"task": info, "raw": raw}


@mcp.tool()
def get_next_task(role: str = "") -> dict:
    """Get the next available task (deps satisfied), optionally filtered by role."""
    result = queue.next_task(BRAIN, role=role)
    if task := result["task"]:
        return {"task": {k: v for k, v in task.items() if k != "raw"}}
    if blocked := result["blocked"]:
        return {"task": None, "blocked": [
            {"id": item["id"], "title": item["title"], "blocked_by": item["blocked_by"]}
            for item in blocked[:5]
        ]}
    return {"task": None}


@mcp.tool()
def add_task(text: str, role: str = "developer", mode: str = "solo",
             priority: str = "P2", council: Optional[list[str]] = None,
             depends_on: Optional[list[str]] = None,
             acceptance: str = "TODO") -> dict:
    """Add a new task to active.md. Returns the generated id."""
    task_id = queue.add(
        text, BRAIN, role=role, mode=mode, priority=priority,
        council=council, depends_on=depends_on, acceptance=acceptance,
    )
    append_log("task-add", task_id, "", f"role={role} mode={mode} prio={priority}")
    git_commit(f"task-add: {task_id}")
    return {"id": task_id, "status": "added"}


@mcp.tool()
def block_task(task_id: str, reason: str, agent_id: str = "") -> dict:
    """Mark task as blocked with reason."""
    agent = str(agent_id or "").strip()
    if not agent:
        return error("agent_id required")
    try:
        queue.block(task_id, BRAIN, agent=agent)
    except Exception as exc:
        return error(str(exc) or "task not found")
    append_log("task-block", task_id, agent, reason)
    git_commit(f"task-block: {task_id} ({reason})")
    return ok()


@mcp.tool()
def get_task_deps(task_id: str) -> dict:
    """Get the dependency tree of a task."""
    return {"tree": queue.deps_tree(task_id, BRAIN)}
