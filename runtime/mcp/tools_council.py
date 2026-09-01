import re
from common import mcp, BRAIN, append_log, git_commit, ts, find_task_block, parse_block, expand_council
from result import ok, error

@mcp.tool()
def council_start(task_id: str) -> dict:
    """Start a council for a task with mode:council. Creates skeleton files."""
    block = find_task_block(task_id)
    if not block:
        return error("task not found")
    info = parse_block(block)
    if not info["council"]:
        return error("task has no council: field")
    roles = expand_council(info["council"])
    cdir = BRAIN / "council" / task_id
    cdir.mkdir(parents=True, exist_ok=True)
    created = []
    for r in roles:
        f = cdir / f"{r}.md"
        if not f.exists():
            f.write_text(f"""---
task: {task_id}
role: {r}
agent: TODO
model: TODO
written: TODO
---

## Position

## Reasoning

## Risks / Open questions

## Recommendation
""")
            created.append(r)
    append_log("council-start", task_id, "", f"roles={','.join(roles)}")
    git_commit(f"council-start: {task_id}", f"council/{task_id}", "wiki/log.md")
    return ok(roles=roles, created=created, directory=str(cdir))

@mcp.tool()
def council_status(task_id: str) -> dict:
    """Get the progress of a council."""
    cdir = BRAIN / "council" / task_id
    if not cdir.exists():
        return error("no council")
    out = {"opinions": [], "synthesis": (cdir / "synthesis.md").exists()}
    for f in sorted(cdir.glob("*.md")):
        if f.name == "synthesis.md":
            continue
        text = f.read_text()
        pending = "written: TODO" in text
        out["opinions"].append({"role": f.stem, "pending": pending})
    return out

@mcp.tool()
def add_council_opinion(task_id: str, role: str, agent_id: str, model: str,
                        position: str, reasoning: str, risks: str,
                        recommendation: str) -> dict:
    """Write your opinion to council/<task_id>/<role>.md.
    Replaces TODO skeleton with actual content."""
    f = BRAIN / "council" / task_id / f"{role}.md"
    if not f.exists():
        return error(f"no opinion file {f}; run council_start first")
    content = f"""---
task: {task_id}
role: {role}
agent: {agent_id}
model: {model}
written: {ts()}
---

## Position
{position}

## Reasoning
{reasoning}

## Risks / Open questions
{risks}

## Recommendation
{recommendation}
"""
    f.write_text(content)
    append_log("council-opinion", task_id, agent_id, f"role={role}")
    git_commit(f"council-opinion: {task_id} by {role}/{agent_id}", f"council/{task_id}", "wiki/log.md")
    return ok(file=str(f))

@mcp.tool()
def get_council_opinions(task_id: str, role: str = "") -> dict:
    """Read opinions in a council. If role given, only that one;
    otherwise all completed opinions (excluding TODO drafts)."""
    cdir = BRAIN / "council" / task_id
    if not cdir.exists():
        return error("no council")
    if role:
        f = cdir / f"{role}.md"
        if not f.exists():
            return error("no such role in council")
        return {"opinions": {role: f.read_text()}}
    out = {}
    for f in cdir.glob("*.md"):
        if f.name == "synthesis.md":
            continue
        text = f.read_text()
        if "written: TODO" in text:
            continue
        out[f.stem] = text
    return {"opinions": out}

@mcp.tool()
def synthesize_council(task_id: str, arbiter_agent: str,
                       positions: dict, agreement: str, disagreement: str,
                       decision: str, reasoning: str,
                       open_questions: str = "",
                       follow_up_tasks: list[str] = None) -> dict:
    """Write synthesis.md as arbiter. positions = {role: tldr}."""
    cdir = BRAIN / "council" / task_id
    if not cdir.exists():
        return error("no council")
    inputs = [f.name for f in cdir.glob("*.md") if f.name != "synthesis.md"]
    pos_lines = "\n".join(f"- {r}: {tldr}" for r, tldr in (positions or {}).items())
    follow = "\n".join(f"- {t}" for t in (follow_up_tasks or []))
    content = f"""---
task: {task_id}
synthesized: {ts()}
arbiter: {arbiter_agent}
inputs: [{', '.join(inputs)}]
---

## Positions (TL;DR)
{pos_lines}

## Agreement
{agreement}

## Disagreement
{disagreement}

## Decision
{decision}

## Why
{reasoning}

## Open questions
{open_questions}

## Follow-up tasks
{follow}
"""
    (cdir / "synthesis.md").write_text(content)
    append_log("council-synth", task_id, arbiter_agent)
    git_commit(f"council-synth: {task_id}", f"council/{task_id}", "wiki/log.md")
    return ok(file=str(cdir / "synthesis.md"))
