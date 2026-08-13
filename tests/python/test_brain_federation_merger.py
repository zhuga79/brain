import pytest
from brain_federation.merger import merge_blocks

def test_merge_blocks_state_priority():
    base = {"id": "t-1", "state": " ", "prio": "P1", "title": "Base"}
    
    # done (x) beats in_progress (~)
    local = {"id": "t-1", "state": "x", "prio": "P1", "title": "Base", "started": "t1", "by": "agent1"}
    remote = {"id": "t-1", "state": "~", "prio": "P1", "title": "Base", "started": "t2", "by": "agent2"}
    
    merged = merge_blocks(base, local, remote)
    assert merged["state"] == "x"
    assert merged["by"] == "agent1"
    
    # in_progress (~) beats blocked (!)
    local2 = {"id": "t-1", "state": "!", "prio": "P1", "title": "Base"}
    merged2 = merge_blocks(base, local2, remote)
    assert merged2["state"] == "~"
    assert merged2["by"] == "agent2"

def test_merge_blocks_fields():
    base = {"id": "t-1", "state": " ", "prio": "P1", "title": "Base", "role": "dev", "acceptance": "A"}
    
    # Only remote changed title
    local = base.copy()
    remote = base.copy()
    remote["title"] = "Remote Title"
    
    merged = merge_blocks(base, local, remote)
    assert merged["title"] == "Remote Title"
    
    # Only local changed prio
    local1b = base.copy()
    local1b["prio"] = "P0"
    remote1b = base.copy()
    merged1b = merge_blocks(base, local1b, remote1b)
    assert merged1b["prio"] == "P0"
    
    # Both changed role -> conflict, pick local
    local2 = base.copy()
    local2["role"] = "architect"
    remote2 = base.copy()
    remote2["role"] = "reviewer"
    
    merged2 = merge_blocks(base, local2, remote2)
    assert merged2["role"] == "architect"

def test_merge_blocks_union_lists():
    base = {"id": "t-1", "state": " ", "prio": "P1", "title": "Base", "deps": ["d1"], "council": []}
    
    local = base.copy()
    local["deps"] = ["d1", "d2"]
    local["council"] = ["legal"]
    
    remote = base.copy()
    remote["deps"] = ["d1", "d3"]
    remote["council"] = ["finance"]
    
    merged = merge_blocks(base, local, remote)
    assert merged["deps"] == ["d1", "d2", "d3"]
    assert merged["council"] == ["finance", "legal"]  # Sorted alphabetically
