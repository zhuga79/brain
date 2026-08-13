"""Conflict resolution for task blocks."""
from __future__ import annotations

from typing import Any
import brain_task_parser


def merge_blocks(base: dict[str, Any], local: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    """Perform a 3-way merge on task block dictionaries."""
    merged = base.copy()
    
    # Priority for states: done (x) > in_progress (~) > blocked (!) > open ( )
    state_rank = {"x": 4, "~": 3, "!": 2, " ": 1}
    
    local_state = local.get("state", " ")
    remote_state = remote.get("state", " ")
    
    if state_rank.get(local_state, 0) > state_rank.get(remote_state, 0):
        merged["state"] = local_state
        merged["started"] = local.get("started", "")
        merged["by"] = local.get("by", "")
    elif state_rank.get(remote_state, 0) > state_rank.get(local_state, 0):
        merged["state"] = remote_state
        merged["started"] = remote.get("started", "")
        merged["by"] = remote.get("by", "")
    else:
        # Same rank, if they are different pick local (or both are 'x' but different agents)
        merged["state"] = local_state
        merged["started"] = local.get("started", "") or remote.get("started", "")
        merged["by"] = local.get("by", "") or remote.get("by", "")

    # For other fields, if only one side changed from base, take it.
    # If both changed, pick local for now (or union for deps).
    fields = ["prio", "title", "role", "mode", "parent", "acceptance"]
    for f in fields:
        b_val = base.get(f)
        l_val = local.get(f)
        r_val = remote.get(f)
        
        if l_val != b_val and r_val == b_val:
            merged[f] = l_val
        elif r_val != b_val and l_val == b_val:
            merged[f] = r_val
        elif l_val != b_val and r_val != b_val:
            # Conflict: both changed. Pick local.
            merged[f] = l_val

    # Deps and Council: Union of lists
    for f in ["deps", "council"]:
        b_set = set(base.get(f, []))
        l_set = set(local.get(f, []))
        r_set = set(remote.get(f, []))
        
        merged[f] = sorted(list(l_set | r_set))

    return merged
