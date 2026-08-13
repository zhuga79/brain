import os
from pathlib import Path
from datetime import date, datetime
import pytest
from brain_learning import (
    ensure_dirs,
    _parse_frontmatter,
    _render_frontmatter,
    new_incident_id,
    new_lesson_id,
    write_incident,
    read_incident,
    list_incidents,
    amend_incident,
    write_lesson,
    read_lesson,
    list_lessons,
    transition_lesson,
    select_lessons_for_injection,
    render_injection_block,
    find_duplicate_active,
    check_wiki_conflict,
    is_expired,
    prune_expired_lessons,
)

# --- Basic Helpers ---

def test_ensure_dirs(tmp_path):
    ensure_dirs(tmp_path)
    assert (tmp_path / "learning" / "incidents").is_dir()
    assert (tmp_path / "learning" / "lessons" / "pending").is_dir()
    assert (tmp_path / "learning" / "summaries").is_dir()

def test_frontmatter_parsing():
    text = "---\nid: inc-1\ntags: [a, b]\n---\nBody content"
    fm, body = _parse_frontmatter(text)
    assert fm == {"id": "inc-1", "tags": ["a", "b"]}
    assert body == "Body content"
    
    # No frontmatter
    assert _parse_frontmatter("just body") == ({}, "just body")
    
    # Unclosed frontmatter
    assert _parse_frontmatter("---") == ({}, "---")

def test_frontmatter_rendering():
    fm = {"id": "les-1", "tags": ["t1", "t2"]}
    body = "Body"
    rendered = _render_frontmatter(fm, body)
    assert rendered.startswith("---")
    assert "id: les-1" in rendered
    assert "tags: [t1, t2]" in rendered
    assert "Body" in rendered

def test_id_generation():
    inc_id = new_incident_id()
    assert inc_id.startswith("inc-")
    assert date.today().strftime("%Y%m%d") in inc_id
    
    les_id = new_lesson_id()
    assert les_id.startswith("les-")

# --- Incident I/O ---

def test_incident_io(tmp_path):
    inc = {"severity": "high"}
    path = write_incident(tmp_path, inc, evidence="Evid", root_cause="RC", fix="Fix")
    assert path.exists()
    
    fm, body = read_incident(tmp_path, inc["id"])
    assert fm["severity"] == "high"
    assert "## Evidence\nEvid" in body
    assert "## Root Cause\nRC" in body
    assert "## Fix\nFix" in body
    
    incidents = list_incidents(tmp_path)
    assert len(incidents) == 1
    assert incidents[0]["id"] == inc["id"]

def test_amend_incident(tmp_path):
    inc = {"id": "inc-1"}
    write_incident(tmp_path, inc, evidence="Original")
    
    ok, msg = amend_incident(tmp_path, "inc-1", root_cause="New RC", fix="New Fix")
    assert ok is True
    
    fm, body = read_incident(tmp_path, "inc-1")
    assert "## Root Cause\nNew RC" in body
    assert "## Fix\nNew Fix" in body
    
    # Amend again (replace)
    amend_incident(tmp_path, "inc-1", root_cause="Better RC")
    _, body2 = read_incident(tmp_path, "inc-1")
    assert "Better RC" in body2
    assert "New RC" not in body2
    assert "New Fix" in body2 # Fix preserved
    
    # Non-existent
    ok2, _ = amend_incident(tmp_path, "missing")
    assert ok2 is False

# --- Lesson I/O & Transitions ---

def test_lesson_io(tmp_path):
    les = {"rule": "Always test"}
    path = write_lesson(tmp_path, les, body="Body")
    assert path.exists()
    assert "pending" in str(path) # default status
    
    fm, body = read_lesson(tmp_path, les["id"])
    assert fm["rule"] == "Always test"
    assert body == "Body"
    
    lessons = list_lessons(tmp_path, "pending")
    assert len(lessons) == 1
    assert lessons[0]["id"] == les["id"]

def test_transition_lesson(tmp_path):
    les = {"id": "les-1", "status": "pending", "rule": "Rule"}
    write_lesson(tmp_path, les)
    
    ok, msg = transition_lesson(tmp_path, "les-1", "approved", approved_by="arbiter-1")
    assert ok is True
    assert "pending → approved" in msg
    
    fm, _ = read_lesson(tmp_path, "les-1")
    assert fm["status"] == "approved"
    assert fm["approved_by"] == "arbiter-1"
    
    # Invalid status
    ok2, _ = transition_lesson(tmp_path, "les-1", "invalid")
    assert ok2 is False

def test_transition_lesson_gates(tmp_path):
    # High severity gate
    les_high = {"id": "les-high", "status": "pending", "severity": "high", "rule": "High Rule"}
    write_lesson(tmp_path, les_high)
    
    # Try activate directly (fail)
    ok1, msg1 = transition_lesson(tmp_path, "les-high", "active")
    assert ok1 is False
    assert "requires arbiter approval" in msg1
    
    # Approve first
    transition_lesson(tmp_path, "les-high", "approved", approved_by="arbiter-1")
    # Now activate (ok)
    ok2, _ = transition_lesson(tmp_path, "les-high", "active")
    assert ok2 is True

    # Duplicate gate
    les_active = {"id": "les-active", "status": "active", "rule": "Same Rule"}
    write_lesson(tmp_path, les_active)
    
    les_new = {"id": "les-new", "status": "pending", "rule": "Same Rule"}
    write_lesson(tmp_path, les_new)
    
    ok3, msg3 = transition_lesson(tmp_path, "les-new", "active")
    assert ok3 is False
    assert "Duplicate lesson detected" in msg3

# --- Injection Logic ---

def test_select_lessons_for_injection(tmp_path):
    write_lesson(tmp_path, {"id": "les-1", "status": "active", "rule": "Rule 1", "roles": ["developer"], "severity": "low"})
    write_lesson(tmp_path, {"id": "les-2", "status": "active", "rule": "Rule 2", "roles": ["developer"], "severity": "high", "tags": ["git"]})
    write_lesson(tmp_path, {"id": "les-3", "status": "active", "rule": "Rule 3", "roles": ["architect"], "severity": "high"})
    
    # Select for developer
    lessons = select_lessons_for_injection(tmp_path, "developer", tags=["git"])
    assert len(lessons) == 2
    assert lessons[0]["id"] == "les-2" # Higher score due to severity and tags
    assert lessons[1]["id"] == "les-1"
    
    # Select for architect
    lessons_arch = select_lessons_for_injection(tmp_path, "architect")
    assert len(lessons_arch) == 1
    assert lessons_arch[0]["id"] == "les-3"

def test_render_injection_block():
    lessons = [
        {"id": "les-1", "rule": "Rule A"},
        {"id": "les-2", "rule": "Rule B"},
    ]
    block = render_injection_block(lessons)
    assert "LEARNED LESSONS" in block
    assert "[les-1] Rule A" in block
    assert "[les-2] Rule B" in block
    assert render_injection_block([]) == ""

# --- Quality Controls ---

def test_check_wiki_conflict(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "p1.md").write_text("---\ntitle: P1\nprotected: true\n---\nSome important rules about python testing.")
    
    # Conflict found
    conflicts = check_wiki_conflict(tmp_path, "Python testing is important")
    assert "P1" in conflicts
    
    # No conflict
    assert check_wiki_conflict(tmp_path, "Something unrelated") == []

def test_is_expired():
    assert is_expired({"expires": "2000-01-01"}) is True
    assert is_expired({"expires": "2099-01-01"}) is False
    assert is_expired({}) is False
    assert is_expired({"expires": "bad-date"}) is False

def test_prune_expired_lessons(tmp_path):
    write_lesson(tmp_path, {"id": "les-expired", "status": "active", "rule": "Old", "expires": "2000-01-01"})
    write_lesson(tmp_path, {"id": "les-fresh", "status": "active", "rule": "New", "expires": "2099-01-01"})
    
    pruned = prune_expired_lessons(tmp_path)
    assert pruned == ["les-expired"]
    
    fm, _ = read_lesson(tmp_path, "les-expired")
    assert fm["status"] == "deprecated"
