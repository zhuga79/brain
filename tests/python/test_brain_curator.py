import os
import sys
import json
import pytest
from pathlib import Path
import importlib.util

# Load brain-curator script as a module
spec = importlib.util.spec_from_loader("brain_curator", importlib.machinery.SourceFileLoader("brain_curator", "runtime/bin/brain-curator"))
brain_curator = importlib.util.module_from_spec(spec)
sys.modules["brain_curator"] = brain_curator
spec.loader.exec_module(brain_curator)

@pytest.fixture
def mock_brain_dir(tmp_path, monkeypatch):
    brain = tmp_path / "brain"
    brain.mkdir()
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    return brain

class DummyArgs:
    pass

def test_curator_monitor_empty(mock_brain_dir):
    args = DummyArgs()
    # Should not crash if dirs are missing
    assert brain_curator.cmd_monitor(args) == 0
    
def test_curator_monitor_lessons(mock_brain_dir):
    lessons_dir = mock_brain_dir / "learning" / "lessons" / "active"
    lessons_dir.mkdir(parents=True)
    
    # 2 identical incidents trigger a starvation wishlist item
    data = {"incident": "Missing framework XYZ error\nstacktrace"}
    (lessons_dir / "les-1.json").write_text(json.dumps(data))
    (lessons_dir / "les-2.json").write_text(json.dumps(data))
    
    # Log with handoffs
    log_dir = mock_brain_dir / "wiki"
    log_dir.mkdir(parents=True)
    (log_dir / "log.md").write_text("orchestrator-handoff | t-1 | test-agent | limit-exhausted\n")
    
    args = DummyArgs()
    assert brain_curator.cmd_monitor(args) == 0
    
    wishlist_path = log_dir / "wishlist.json"
    assert wishlist_path.exists()
    wishlist = json.loads(wishlist_path.read_text())
    
    assert len(wishlist) == 2
    types = [w["type"] for w in wishlist]
    assert "error_resolution" in types
    assert "fleet_starvation" in types

def test_curator_search_and_synthesize(mock_brain_dir):
    log_dir = mock_brain_dir / "wiki"
    log_dir.mkdir(parents=True)
    
    # Setup initial wishlist
    wishlist = [
        {"type": "fleet_starvation", "trigger": "test-agent hit rate limit", "status": "pending_search"},
        {"type": "error_resolution", "trigger": "Missing framework XYZ", "status": "pending_search"}
    ]
    (log_dir / "wishlist.json").write_text(json.dumps(wishlist))
    
    args = DummyArgs()
    # Run search
    assert brain_curator.cmd_search(args) == 0
    
    updated = json.loads((log_dir / "wishlist.json").read_text())
    assert updated[0]["status"] == "synthesizing"
    assert "discovery" in updated[0]
    
    # Run synthesize
    assert brain_curator.cmd_synthesize(args) == 0
    
    final = json.loads((log_dir / "wishlist.json").read_text())
    assert final[0]["status"] == "proposed"
    assert "proposal_path" in final[0]
    
    prop_dir = log_dir / "proposals"
    assert prop_dir.exists()
    assert len(list(prop_dir.glob("*.md"))) == 2

def test_curator_rank_models(mock_brain_dir):
    args = DummyArgs()
    assert brain_curator.cmd_rank(args) == 0
    
    report_path = mock_brain_dir / "wiki" / "model-fleet-report.md"
    assert report_path.exists()
    assert "Best efficient model: gemini-1.5-flash" in report_path.read_text()

def test_curator_monitor_limits(mock_brain_dir):
    log_dir = mock_brain_dir / "wiki"
    log_dir.mkdir(parents=True)
    
    log_text = """
orchestrator-handoff | t-1 | agent-a | limit-exhausted
orchestrator-handoff | t-2 | agent-a | limit-exhausted
orchestrator-handoff | t-3 | agent-a | rate-limit
orchestrator-handoff | t-4 | agent-b | limit-exhausted
"""
    (log_dir / "log.md").write_text(log_text)
    
    args = DummyArgs()
    assert brain_curator.cmd_monitor_limits(args) == 0
    
    health_path = mock_brain_dir / ".provider-health.json"
    assert health_path.exists()
    
    health = json.loads(health_path.read_text())
    assert health["clients"]["agent-a"]["errors"] == 3
    assert health["clients"]["agent-a"]["status"] == "CRITICAL"
    assert health["clients"]["agent-b"]["errors"] == 1
    assert health["clients"]["agent-b"]["status"] == "DEGRADED"
