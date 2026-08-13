import pytest
from brain_handoff_detector import detect_limit

def test_detect_limit_exhausted():
    text = "Error: You've hit your limit · resets in 5 hours"
    res = detect_limit(text)
    assert res is not None
    assert res["reason"] == "limit-exhausted"

def test_detect_rate_limit():
    text = "HTTP 429 Too Many Requests: please try again later"
    res = detect_limit(text)
    assert res is not None
    assert res["reason"] == "rate-limit"

def test_detect_limit_none():
    text = "Everything is working perfectly fine."
    res = detect_limit(text)
    assert res is None

def test_detect_limit_empty():
    assert detect_limit("") is None
    assert detect_limit(None) is None

def test_detect_resource_exhausted():
    text = "RESOURCE_EXHAUSTED: quota exceeded"
    res = detect_limit(text)
    assert res is not None
    assert res["reason"] == "limit-exhausted"

# --- t-2026-06-26-handoff-semantic: semantic "needs human" detection ---
from brain_handoff_detector import detect_needs_human, detect_handoff

def test_detect_needs_human_marker():
    res = detect_needs_human("Blocked: NEEDS_HUMAN — cannot decide pricing without owner")
    assert res is not None and res["reason"] == "needs-human"

def test_detect_needs_human_waiting_approval():
    res = detect_needs_human("Status: waiting-approval before release")
    assert res is not None and res["reason"] == "needs-human"

def test_detect_needs_human_none():
    assert detect_needs_human("normal agent output, all good") is None

def test_detect_handoff_prefers_limit():
    # rate-limit must not regress even if both signals present
    res = detect_handoff("429 Too Many Requests; also NEEDS_HUMAN")
    assert res is not None and res["reason"] == "rate-limit"

def test_detect_handoff_needs_human():
    res = detect_handoff("All compute fine but NEEDS_HUMAN to choose option")
    assert res is not None and res["reason"] == "needs-human"

def test_detect_handoff_none():
    assert detect_handoff("everything works") is None
