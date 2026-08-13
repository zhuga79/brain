import os
import json
import pytest
import time
import re
import shutil
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

from brain_dashboard.data import (
    collect_status,
    collect_scheduled_jobs,
    collect_workspaces,
    save_snapshot,
    load_snapshot,
    compute_delta,
    collect_learning_stats,
    read_index,
    read_graph,
    collect_metrics,
    read_audit_log,
    read_obsidian_views,
    read_handoff_journal,
    collect_handoff_status,
    brain_path,
    summarize_tasks,
)

# Внутренние помощники берём у модулей-владельцев: brain_dashboard.data — точка
# входа для сбора, а не место, где живёт каждая частная функция.
from brain_dashboard.collect.council import (
    _council_role_map,
    _council_synthesis_done,
    _frontmatter_value,
    _section_has_text,
)
from brain_dashboard.collect.learning import _read_frontmatter

@pytest.fixture
def mock_brain(tmp_path, monkeypatch):
    brain = tmp_path / "brain"
    brain.mkdir()
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    
    (brain / "tasks").mkdir()
    (brain / "wiki").mkdir()
    (brain / ".locks").mkdir()
    (brain / "council").mkdir()
    (brain / "learning" / "incidents").mkdir(parents=True)
    (brain / "learning" / "lessons" / "active").mkdir(parents=True)
    (brain / "learning" / "lessons" / "pending").mkdir(parents=True)
    (brain / "learning" / "lessons" / "approved").mkdir(parents=True)
    (brain / "learning" / "lessons" / "deprecated").mkdir(parents=True)
    (brain / "learning" / "lessons" / "rejected").mkdir(parents=True)
    (brain / ".brain" / "index").mkdir(parents=True)
    (brain / "handoff").mkdir()
    (brain / ".policy").mkdir()
    (brain / ".webhooks").mkdir()
    
    return brain

def test_brain_path(mock_brain, monkeypatch):
    assert brain_path("foo") == Path("foo")
    monkeypatch.setenv("BRAIN_PATH", str(mock_brain))
    assert brain_path() == mock_brain

def test_parse_tasks(mock_brain):
    """Очередь читается через queue.load_active, не через осиротевший парсер дашборда."""
    from brain_app import queue
    assert queue.load_active(mock_brain) == []
    (mock_brain / "tasks" / "active.md").write_text("- [ ] [P1] t1 — Test\n")
    tasks = queue.load_active(mock_brain)
    assert len(tasks) == 1

def test_summarize_tasks():
    active = [{"state": " ", "priority": "P1", "role": "dev", "mode": "solo"}]
    summary = summarize_tasks(active, [])
    assert summary["active_count"] == 1
    
    active2 = [{"state": " ", "priority": "P1", "role": None, "mode": None}]
    summary2 = summarize_tasks(active2, [])
    assert summary2["roles"]["unassigned"] == 1
    assert summary2["modes"]["unspecified"] == 1


def test_summarize_tasks_has_no_clients_aggregation():
    """Корневая очередь не несёт client: — агрегация clients снята, а не пустеет."""
    active = [
        {"state": " ", "priority": "P1", "role": "dev", "mode": "solo", "client": "ООО Ромашка"},
        {"state": " ", "priority": "P2", "role": "dev", "mode": "solo"},
    ]
    summary = summarize_tasks(active, [])
    assert "clients" not in summary

def test_collect_status_missing_dirs(tmp_path, monkeypatch):
    brain = tmp_path / "empty"
    brain.mkdir()
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    status = collect_status(brain)
    assert status["tasks"]["summary"]["active_count"] == 0
    assert "scheduled" in status

def test_collect_scheduled_jobs_parses_read_only_sources(monkeypatch):
    def fake_run(cmd, **kwargs):
        joined = " ".join(cmd)
        if cmd == ["crontab", "-l"]:
            return type("R", (), {"returncode": 0, "stdout": "# comment\n*/15 * * * * brain-dashboard export\n", "stderr": ""})()
        if joined.startswith("systemctl --user list-timers"):
            return type("R", (), {"returncode": 0, "stdout": "NEXT LEFT LAST PASSED UNIT ACTIVATES\nFri 2026-05-29 1h left n/a n/a brain-sync.timer brain-sync.service\n", "stderr": ""})()
        if cmd == ["atq"]:
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": "permission denied"})()
        raise AssertionError(cmd)

    monkeypatch.setattr("subprocess.run", fake_run)

    scheduled = collect_scheduled_jobs()

    assert scheduled["summary"]["cron"] == 1
    assert scheduled["summary"]["systemd_timers"] == 1
    assert scheduled["summary"]["at"] == 0
    assert scheduled["cron"]["items"][0]["command"] == "brain-dashboard export"
    assert scheduled["systemd_timers"]["items"][0]["unit"] == "brain-sync.timer"
    assert scheduled["at"]["status"] == "error"

def test_collect_workspaces_uses_configured_roots_only(tmp_path, monkeypatch):
    root = tmp_path / "docs"
    ws = root / "project-a"
    ws.mkdir(parents=True)
    (ws / "BRAIN.md").write_text("# Workspace: Project A\n", encoding="utf-8")
    (ws / "TASKS.md").write_text(
        """# Local Tasks

- [ ] [P1] local-001 - Review draft
      role: lawyer
      acceptance: Checked.
""",
        encoding="utf-8",
    )
    (ws / "LOG.md").write_text("# Local Log\n\n## 2026-05-28T10:00:00Z | agent-a | created\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_DASHBOARD_WORKSPACE_ROOTS", str(root))

    data = collect_workspaces()

    assert data["configured"] is True
    assert data["summary"]["count"] == 1
    assert data["summary"]["open_tasks"] == 1
    assert data["items"][0]["title"] == "Project A"  # prefix stripped
    assert data["items"][0]["next_task"]["task_id"] == "local-001"

def test_read_locks_edge_cases(mock_brain):
    lock_dir = mock_brain / ".locks" / "t-1"
    lock_dir.mkdir()
    (lock_dir / "owner").write_text("agent-1|invalid|ttl")
    status = collect_status(mock_brain)
    assert status["locks"]["items"][0]["age_seconds"] is None
    
    (lock_dir / "owner").write_text(f"agent-1|{int(time.time())-60}|600")
    status2 = collect_status(mock_brain)
    assert status2["locks"]["items"][0]["age_seconds"] >= 60

def test_council_details(mock_brain):
    (mock_brain / "tasks" / "active.md").write_text("- [ ] [P1] t-1 — Test\n      council: [legal, dev, extra]\n- [ ] [P1] t-2 — NoCouncil\n")
    council_dir = mock_brain / "council" / "t-1"
    council_dir.mkdir()
    (council_dir / "legal.md").write_text("---\nwritten: 2026-05-15\nagent: a1\n---\n## Position\nAccept\n\n## Recommendation\nGo\n")
    (council_dir / "dev.md").write_text("---\nwritten: TODO\nagent: TODO\n---\n")
    (council_dir / "synthesis.md").write_text("---\nsynthesized: 2026-05-15\narbiter: a2\n---\n")
    
    status = collect_status(mock_brain)
    c = status["council"]["items"][0]
    states = {op["role"]: op["status"] for op in c["opinions"]}
    assert states["legal"] == "valid"
    assert states["dev"] == "invalid"
    assert states["extra"] == "missing"
    assert c["synthesis"]["status"] == "done"
    
    (council_dir / "synthesis.md").write_text("---\nsynthesized: TODO\n---")
    status2 = collect_status(mock_brain)
    assert status2["council"]["items"][0]["synthesis"]["status"] == "not_ready"
    
    (council_dir / "dev.md").write_text("---\nwritten: 2026-05-15\nagent: a1\n---\n## Position\nx\n## Recommendation\ny\n")
    (mock_brain / "tasks" / "active.md").write_text("- [ ] [P1] t-1 — Test\n      council: [legal, dev]\n")
    (council_dir / "synthesis.md").unlink()
    status3 = collect_status(mock_brain)
    assert status3["council"]["items"][0]["synthesis"]["status"] == "ready"

def test_council_synthesis_done_edge():
    assert _council_synthesis_done(Path("missing")) is False

def test_council_role_map(mock_brain):
    (mock_brain / "tasks" / "active.md").write_text("- [ ] [P1] t1 — T\n      council: [r1]\n")
    (mock_brain / "tasks" / "done.md").write_text("- [x] [P1] t2 — T\n      council: [r2]\n")
    m = _council_role_map(mock_brain)
    assert m["t1"] == ["r1"]
    assert m["t2"] == ["r2"]

def test_read_audit_log(mock_brain):
    log_path = mock_brain / "wiki" / "log.md"
    log_path.write_text("## [now] op | t1 | a1 | extra\ninvalid line\n")
    entries = read_audit_log(mock_brain)
    assert len(entries) == 1
    assert len(read_audit_log(mock_brain, task_filter="t2")) == 0
    log_path.unlink()
    assert read_audit_log(mock_brain) == []

def test_read_obsidian_views(mock_brain, monkeypatch):
    monkeypatch.setattr("brain_wiki.OBSIDIAN_EXPECTED_VIEWS", ["view1"])
    v_dir = mock_brain / "wiki" / "_views"
    v_dir.mkdir(exist_ok=True)
    (v_dir / "view1").touch()
    assert read_obsidian_views(mock_brain)["view1"] is True
    shutil.rmtree(v_dir)
    assert read_obsidian_views(mock_brain)["view1"] is False

def test_read_handoff_journal(mock_brain):
    j1 = mock_brain / "handoff" / "journal-2026-05-15.ndjson"
    # Content with empty line and invalid JSON and hitting limit
    j1.write_text('{"id": 1}\n\n{"id": 2}\ninvalid\n{"id": 3}\n')
    entries = read_handoff_journal(mock_brain, limit=2)
    assert len(entries) == 2
    assert entries[0]["id"] == 3
    assert entries[1]["id"] == 2
    
    # Not hitting limit
    assert len(read_handoff_journal(mock_brain, limit=10)) == 3

    j1.chmod(0)
    assert len(read_handoff_journal(mock_brain)) == 0
    j1.chmod(0o644)
    shutil.rmtree(mock_brain / "handoff")
    assert read_handoff_journal(mock_brain) == []

def test_collect_handoff_status(mock_brain):
    h_dir = mock_brain / "handoff"
    h_dir.mkdir(exist_ok=True)
    h_path = h_dir / "ORCHESTRATOR_HANDOFF.md"
    # More than 8 commands
    cmds = "\n".join(f"cmd{i}" for i in range(10))
    h_path.write_text(f"reason: limit\nfrom_agent: a1\n## Next Commands\n```bash\n{cmds}\n```")
    status = collect_handoff_status(mock_brain)
    assert status["reason"] == "limit"
    assert len(status["commands"]) == 8
    
    with patch("pathlib.Path.read_text", side_effect=OSError("fail")):
        assert collect_handoff_status(mock_brain)["exists"] is True

def test_snapshots_and_delta(mock_brain):
    assert load_snapshot(mock_brain) is None
    status = {
        "tasks": {"active": [{"id": "t-1", "state": "~"}], "done": [{"id": "t-2"}]},
        "locks": {"items": [{"task_id": "t-1"}]},
        "council": {"items": [{"task_id": "t-1"}]}
    }
    save_snapshot(mock_brain, status)
    loaded = load_snapshot(mock_brain)
    assert loaded["task_ids"]["t-1"] == "~"
    (mock_brain / "wiki" / "_views" / "brain-dashboard-snapshot.json").write_text("invalid")
    assert load_snapshot(mock_brain) is None
    new_status = {
        "tasks": {"active": [{"id": "t-1", "state": "x"}], "done": [{"id": "t-2"}, {"id": "t-1"}]},
        "locks": {"items": []},
        "council": {"items": []}
    }
    delta = compute_delta(loaded, new_status)
    assert "t-1" in delta["tasks_completed"]
    assert compute_delta(None, new_status)["has_delta"] is False

def test_collect_learning_stats(mock_brain):
    (mock_brain / "learning" / "incidents" / "inc-1.md").write_text("---\nid: i1\nunknown: x\n---")
    (mock_brain / "learning" / "lessons" / "active" / "les-1.md").write_text("---\nid: L1\nstatus: active\nrule: test\n---")
    shutil.rmtree(mock_brain / "learning" / "lessons" / "pending")
    stats = collect_learning_stats(mock_brain)
    assert stats["counts"]["incidents"] == 1
    assert stats["recent_incidents"][0]["id"] == "i1"

def test_read_index_graph(mock_brain, monkeypatch):
    idx_dir = mock_brain / ".brain" / "index"
    (idx_dir / "manifest.json").write_text('{"pages": 1}')
    with patch("brain_index.index_status", return_value={"status": "ok", "health": "ok", "pages": 1}):
        assert read_index(mock_brain)["next_step"] == ""
    with patch("brain_index.index_status", return_value={"status": "ok", "health": "stale", "pages": 1}):
        assert read_index(mock_brain)["next_step"] == "brain-index rebuild"
    (idx_dir / "links.json").write_text('{"nodes": [{"id": "1", "type": "wiki"}]}')
    (idx_dir / "graph.json").write_text('{"nodes": [{"id": "1", "type": "wiki"}], "edges": [{"from": "1", "to": "2"}]}')
    assert read_graph(mock_brain)["available"] is True
    (idx_dir / "graph.json").unlink()
    assert read_graph(mock_brain)["available"] is False

def test_read_graph_failure(mock_brain):
    idx_dir = mock_brain / ".brain" / "index"
    idx_dir.mkdir(exist_ok=True)
    g_path = idx_dir / "graph.json"
    g_path.write_text("invalid json")
    assert read_graph(mock_brain)["available"] is False

def test_collect_metrics(mock_brain):
    (mock_brain / ".webhooks" / "dead-letter.jsonl").write_text('{"id":1}\n')
    (mock_brain / ".policy" / "last-check.json").write_text('{"ok": true, "gates_passed": 1, "last_run": "2026-05-15T00:00:00Z"}')
    tm_path = mock_brain / ".brain" / "token-metrics.jsonl"
    tm_path.write_text('{"raw_bytes": 100, "compact_bytes": 50}\ninvalid\n\n{"raw_bytes": 0, "compact_bytes": 0}\n')
    metrics = collect_metrics(mock_brain)
    assert metrics["webhook"]["dead_letter_count"] == 1
    assert metrics["token_economy"]["commands"] == 2
    (mock_brain / ".policy" / "last-check.json").write_text('{"ok": true, "last_run": "invalid date"}')
    assert collect_metrics(mock_brain)["policy"]["age_seconds"] is None
    with patch("pathlib.Path.read_text", side_effect=OSError):
        assert collect_metrics(mock_brain)["webhook"]["dead_letter_count"] == 0
    (mock_brain / ".policy" / "last-check.json").write_text("invalid")
    assert collect_metrics(mock_brain)["policy"]["status"] == "error"

def test_frontmatter_edge_cases(tmp_path):
    p = tmp_path / "test.md"
    p.write_text("no frontmatter")
    assert _read_frontmatter(p, {"a"}) == {}
    p.write_text("---\na: 1")
    assert _read_frontmatter(p, {"a"}) == {}
    p.write_text("---\na: 1\nno_colon\nignored: 2\nb: [x, y]\n---\n")
    fm = _read_frontmatter(p, {"a", "b"})
    assert fm["a"] == "1"
    assert fm["b"] == ["x", "y"]
    assert "ignored" not in fm
    with patch("pathlib.Path.read_text", side_effect=OSError):
        assert _read_frontmatter(p, {"a"}) == {}

def test_utils():
    assert _section_has_text("## Foo\nbar", "Foo") is True
    assert _section_has_text("## Foo\n", "Foo") is False
    assert _frontmatter_value("agent: foo", "agent") == "foo"
    assert _frontmatter_value("foo", "agent") == ""


def test_parse_tasks_surface_field(mock_brain):
    """queue.load_active exposes effective surface (t-2026-06-26-dashboard-badge)."""
    from brain_app import queue
    task_dir = mock_brain / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "active.md").write_text(
        "- [ ] [P1] t-hdl — Headless task  role: developer  mode: solo\n"
    )
    (task_dir / "done.md").write_text("", encoding="utf-8")
    tasks = queue.load_active(mock_brain)
    assert len(tasks) == 1
    assert tasks[0].get("surface") == "headless"

    (task_dir / "active.md").write_text(
        "- [ ] [P1] t-int — Interactive task  role: designer  mode: solo\n"
    )
    tasks = queue.load_active(mock_brain)
    assert len(tasks) == 1
    assert tasks[0].get("surface") == "interactive"

    (task_dir / "active.md").write_text(
        "- [ ] [P1] t-exp — Explicit task  role: developer  mode: solo\n"
        "      surface: interactive\n"
    )
    tasks = queue.load_active(mock_brain)
    assert len(tasks) == 1
    assert tasks[0].get("surface") == "interactive"


def test_summarize_tasks_surfaces_counter():
    """summarize_tasks must include a surfaces counter (t-2026-06-26-dashboard-badge)."""
    active = [
        {"state": " ", "priority": "P1", "role": "developer", "mode": "solo", "surface": "headless"},
        {"state": " ", "priority": "P1", "role": "designer", "mode": "solo", "surface": "interactive"},
        {"state": " ", "priority": "P1", "role": "developer", "mode": "solo", "surface": "headless"},
    ]
    summary = summarize_tasks(active, [])
    assert "surfaces" in summary
    assert summary["surfaces"]["headless"] == 2
    assert summary["surfaces"]["interactive"] == 1



def test_save_snapshot_includes_surfaces(tmp_path):
    """t-2026-06-26-dashboard-badge: snapshot carries a surface distribution."""
    import json as _json
    from brain_dashboard.collect.snapshot import _snapshot_path
    from brain_dashboard.data import save_snapshot
    status = {
        "tasks": {
            "active": [
                {"id": "t-a", "state": " ", "surface": "interactive"},
                {"id": "t-b", "state": " ", "surface": "headless"},
            ],
            "done": [],
        },
        "locks": {"items": []},
        "council": {"items": []},
    }
    (tmp_path / "wiki" / "_views").mkdir(parents=True)
    save_snapshot(tmp_path, status)
    snap = _json.loads(_snapshot_path(tmp_path).read_text())
    assert "surfaces" in snap
    assert snap["surfaces"]["interactive"] == 1
    assert snap["surfaces"]["headless"] == 1


def test_default_workspace_roots_home(monkeypatch):
    import brain_dashboard.collect.workspaces as D
    monkeypatch.delenv("BRAIN_DASHBOARD_WORKSPACE_ROOTS", raising=False)
    monkeypatch.delenv("BRAIN_WORKSPACE_ROOTS", raising=False)
    roots, auto = D._workspace_roots_from_env()
    from pathlib import Path
    assert roots == [Path.home()] and auto is True


def test_explicit_workspace_roots(monkeypatch):
    import brain_dashboard.collect.workspaces as D
    monkeypatch.setenv("BRAIN_DASHBOARD_WORKSPACE_ROOTS", "/a:/b")
    roots, auto = D._workspace_roots_from_env()
    assert [str(r) for r in roots] == ["/a", "/b"] and auto is False


def test_workspaces_sorted_by_recency(tmp_path, monkeypatch):
    import os, time, brain_dashboard.data as D
    older = tmp_path / "older"; newer = tmp_path / "newer"
    for d, t in ((older, "# Older\n"), (newer, "# Newer\n")):
        d.mkdir(); (d / "BRAIN.md").write_text(t)
    # make `newer` more recently modified
    os.utime(older / "BRAIN.md", (time.time() - 1000, time.time() - 1000))
    os.utime(newer / "BRAIN.md", None)
    monkeypatch.setenv("BRAIN_DASHBOARD_WORKSPACE_ROOTS", str(tmp_path))
    monkeypatch.setenv("BRAIN_DASHBOARD_WS_CACHE_TTL", "0")  # bypass cache
    data = D.collect_workspaces()
    titles = [it["title"] for it in data["items"]]
    assert titles == ["Newer", "Older"]  # most recently changed first (leftmost)
