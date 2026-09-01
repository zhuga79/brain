import json
import datetime
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch
import argparse

import pytest
from brain_federation.plan import (
    utc_now,
    sha256_text,
    sha256_file,
    canonical_json,
    plan_id,
    task_refs,
    plan_task_imports,
    git_status,
    git_head_sha,
    source_state,
    plan_wiki_changes,
    required_confirmations,
    build_plan,
    load_plan,
    task_import_block,
    task_import_validation,
    live_task_conflicts,
    stale_plan_findings,
    acquire_import_lock,
    release_import_lock,
    append_imports_atomic,
    log_imports,
    import_result,
    proposal_gate_findings,
    proposal_result,
    proposal_meta,
    write_proposal_artifacts,
    cmd_plan,
    cmd_import_tasks,
    cmd_write_wiki_proposals,
    Finding,
)

# --- Hashing & Basic Helpers ---

def test_utc_now():
    now = utc_now()
    assert "T" in now
    assert "Z" in now
    # Verify format YYYY-MM-DDTHH:MM:SSZ
    datetime.datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ")

def test_sha256_text():
    text = "hello"
    expected = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert sha256_text(text) == expected

def test_sha256_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("content")
    expected = "sha256:" + hashlib.sha256(b"content").hexdigest()
    assert sha256_file(f) == expected
    
    # Non-existent file
    assert sha256_file(tmp_path / "missing.txt") == sha256_text("")

def test_canonical_json():
    data = {"b": 2, "a": 1}
    assert canonical_json(data) == '{"a":1,"b":2}'

def test_plan_id():
    data = {
        "plan_id": "old",
        "generated_at": "now",
        "payload": "data"
    }
    # should ignore plan_id and generated_at
    id1 = plan_id(data)
    id2 = plan_id({"payload": "data"})
    assert id1 == id2
    assert id1.startswith("sha256:")

def test_task_refs():
    tasks = [
        {"id": "t1", "val": "a"},
        {"id": "t2", "val": "b"},
    ]
    refs = task_refs(tasks)
    assert refs["t1"] == tasks[0]
    assert refs["t2"] == tasks[1]

# --- Task Helpers ---

def test_plan_task_imports(tmp_path):
    repo = tmp_path / "repo"
    brain = tmp_path / "brain"
    (repo / "tasks").mkdir(parents=True)
    (brain / "tasks").mkdir(parents=True)
    
    repo_active = [
        {"id": "t1", "title": "T1", "priority": "P1", "state": " "},
        {"id": "t2", "title": "T2", "priority": "P2", "state": "x"}, # skipped: state-x
        {"id": "t3", "title": "T3", "priority": "P1", "state": " "}, # skipped: already-active
        {"id": "t4", "title": "T4", "priority": "P1", "state": " "}, # skipped: already-done
        {"id": "t1", "title": "T1-dup", "priority": "P1", "state": " "}, # skipped: duplicate-in-repo
    ]
    brain_active = [{"id": "t3", "title": "T3", "priority": "P1", "state": " "}]
    brain_done = [{"id": "t4", "title": "T4", "priority": "P1", "state": "x"}]
    
    with patch("brain_federation.plan.parse_task_file_optional") as mock_parse:
        def side_effect(path, src, **kwargs):
            if "repo/tasks/active.md" in str(path): return repo_active, []
            if "repo/tasks/done.md" in str(path): return [], []
            if "brain/tasks/active.md" in str(path): return brain_active, []
            if "brain/tasks/done.md" in str(path): return brain_done, []
            return [], []
        mock_parse.side_effect = side_effect
        
        with patch("brain_federation.plan.check_duplicates", return_value=[]), \
             patch("brain_federation.plan.check_cross_file_conflicts", return_value=[]):
            
            imports, skipped, findings = plan_task_imports(repo, brain)
            
            assert len(imports) == 1
            assert imports[0]["id"] == "t1"
            
            reasons = [s["reason"] for s in skipped]
            assert "state-x" in reasons
            assert "already-active" in reasons
            assert "already-done" in reasons
            assert "duplicate-in-repo" in reasons

def test_task_import_block():
    task = {
        "id": "t1", "title": "Title", "priority": "P1", 
        "role": "dev", "mode": "solo", "acceptance": "acc",
        "path": "p.md", "line": 10
    }
    block = task_import_block(task)
    assert "- [ ] [P1] t1 — Title" in block
    assert "role: dev   mode: solo" in block
    assert "acceptance: acc" in block
    assert "ref: p.md:10" in block

    # Minimal
    task_min = {
        "id": "t2", "title": "Title2", "priority": "P2", 
        "acceptance": "acc2", "source": "repo"
    }
    block_min = task_import_block(task_min)
    assert "role: developer   mode: solo" in block_min
    assert "ref: repo" in block_min

def test_task_import_validation():
    # Valid
    valid = [{"id": "t-1", "title": "T", "priority": "P1", "acceptance": "A", "state": "open"}]
    assert task_import_validation(valid) == []
    
    # Invalid
    invalid = [
        {"id": "bad id", "state": "open"}, # bad id, missing title/prio/acc
        {"id": "t-1", "title": "T", "priority": "P1", "acceptance": "A", "state": "done"}, # bad state
        {"id": "t-2", "title": "T", "priority": "P9", "acceptance": "A", "state": "open"}, # bad prio
        {"id": "t-1", "title": "T", "priority": "P1", "acceptance": "A", "state": "open"}, # duplicate id
    ]
    findings = task_import_validation(invalid)
    codes = [f.code for f in findings]
    assert "plan-schema-mismatch" in codes
    assert "task-state-not-open" in codes
    assert "task-duplicate-id-at-write" in codes

def test_live_task_conflicts(tmp_path):
    brain = tmp_path
    (brain / "tasks").mkdir()
    
    active = [{"id": "t1", "path": "active.md", "line": 1}]
    done = [{"id": "t2", "path": "done.md", "line": 5}]
    
    with patch("brain_federation.plan.parse_task_file_optional") as mock_parse:
        def side_effect(path, src, **kwargs):
            if "active.md" in str(path): return active, []
            if "done.md" in str(path): return done, []
            return [], []
        mock_parse.side_effect = side_effect
        
        imports = [
            {"id": "t1", "title": "T1"}, # conflict active
            {"id": "t2", "title": "T2"}, # conflict done
            {"id": "t3", "title": "T3"}, # ok
        ]
        findings = live_task_conflicts(brain, imports)
        assert len(findings) == 2
        assert all(f.code == "task-duplicate-id-at-write" for f in findings)

# --- Source State & Plan Building ---

def test_git_status_and_head(tmp_path):
    repo = tmp_path
    with patch("brain_federation.plan.is_git_repo", return_value=True):
        with patch("brain_federation.plan.git_run") as mock_git:
            mock_git.return_value = MagicMock(stdout=" M f1\n?? f2\n", returncode=0)
            status = git_status(repo)
            assert status == [" M f1", "?? f2"]
            
            mock_git.return_value = MagicMock(stdout="abcdef\n", returncode=0)
            assert git_head_sha(repo) == "abcdef"

    with patch("brain_federation.plan.is_git_repo", return_value=False):
        assert git_status(repo) == []
        assert git_head_sha(repo) == ""

def test_source_state(tmp_path):
    repo = tmp_path / "repo"
    brain = tmp_path / "brain"
    (brain / "tasks").mkdir(parents=True)
    (brain / "tasks" / "active.md").write_text("active")
    (brain / "tasks" / "done.md").write_text("done")
    
    with patch("brain_federation.plan.git_status", return_value=["M f1"]), \
         patch("brain_federation.plan.git_head_sha", return_value="abc"):
        state = source_state(repo, brain)
        assert state["repo_head"] == "abc"
        assert state["repo_status"] == ["M f1"]
        assert "brain_active_sha256" in state

def test_plan_wiki_changes(tmp_path):
    repo = tmp_path / "repo"
    brain = tmp_path / "brain"
    (repo / "wiki").mkdir(parents=True)
    (brain / "wiki").mkdir(parents=True)
    
    (repo / "wiki" / "p1.md").write_text("new")
    (brain / "wiki" / "p1.md").write_text("old")
    
    changed = {"wiki/p1.md", "other.txt"}
    findings = [Finding("protected-wiki-edit", "block", "wiki/p1.md", "msg")]
    
    with patch("brain_federation.plan.frontmatter", return_value={"curation": "human"}):
        proposals, skipped = plan_wiki_changes(repo, brain, changed, findings)
        assert len(proposals) == 1
        assert proposals[0]["path"] == "wiki/p1.md"
        assert proposals[0]["reason"] == "protected-wiki-edit"

def test_build_plan(tmp_path):
    repo = tmp_path / "repo"
    brain = tmp_path / "brain"
    
    with patch("brain_federation.plan.collect_preflight", return_value=({"ok": True}, [], {"wiki/p1.md"})), \
         patch("brain_federation.plan.plan_task_imports", return_value=([], [], [])), \
         patch("brain_federation.plan.plan_wiki_changes", return_value=([], [])), \
         patch("brain_federation.plan.source_state", return_value={}):
        
        plan, findings = build_plan(repo, brain)
        assert plan["kind"] == "federation-plan"
        assert "plan_id" in plan

def test_load_plan(tmp_path):
    f = tmp_path / "plan.json"
    
    # Valid
    data = {
        "schema_version": 1,
        "mode": "plan",
        "source_state": {
            "repo_head": "a", "repo_status_sha256": "b",
            "brain_active_sha256": "c", "brain_done_sha256": "d"
        },
        "task_imports": []
    }
    f.write_text(json.dumps(data))
    plan, findings, rc = load_plan(f)
    assert plan == data
    assert rc == 0
    
    # Schema mismatch
    data["mode"] = "exec"
    f.write_text(json.dumps(data))
    _, findings, rc = load_plan(f)
    assert any(f.code == "plan-schema-mismatch" for f in findings)
    assert rc == 1

    # Unreadable
    _, findings, rc = load_plan(tmp_path / "missing.json")
    assert any(f.code == "plan-unreadable" for f in findings)
    assert rc == 2

def test_stale_plan_findings():
    plan = {
        "source_state": {"repo_head": "old", "repo_status_sha256": "old"}
    }
    args = argparse.Namespace(allow_drift=False, allow_stale=False)
    
    with patch("brain_federation.plan.source_state", return_value={"repo_head": "new", "repo_status_sha256": "old"}):
        findings = stale_plan_findings(plan, args)
        assert len(findings) == 1
        assert findings[0].code == "plan-stale"
        
        # With allow_drift
        args.allow_drift = True
        assert stale_plan_findings(plan, args) == []

# --- Import Lock Helpers ---

def test_import_lock(tmp_path):
    brain = tmp_path
    agent = "test-agent"
    
    # Acquire
    ok, owner = acquire_import_lock(brain, agent)
    assert ok is True
    assert (brain / ".locks" / "tasks-active" / "owner").exists()
    
    # Conflict
    ok2, owner2 = acquire_import_lock(brain, "other")
    assert ok2 is False
    assert owner2 == agent
    
    # Release
    release_import_lock(brain, agent)
    assert not (brain / ".locks" / "tasks-active" / "owner").exists()

def test_import_lock_stale(tmp_path):
    brain = tmp_path
    agent = "test-agent"
    
    # Create stale lock
    lock_dir = brain / ".locks" / "tasks-active"
    lock_dir.mkdir(parents=True)
    (lock_dir / "owner").write_text("old-agent|1000|10", encoding="utf-8")
    
    # Should override
    with patch("time.time", return_value=2000):
        ok, owner = acquire_import_lock(brain, agent)
        assert ok is True
        assert "test-agent" in (lock_dir / "owner").read_text()

# --- Import/Writing Logic ---

def test_append_imports_atomic(tmp_path):
    brain = tmp_path
    (brain / "tasks").mkdir()
    active = brain / "tasks" / "active.md"
    active.write_text("# Active tasks\n\n- [ ] [P1] existing\n")

    imports = [{"id": "t1", "title": "New", "priority": "P2", "acceptance": "A"}]
    findings = append_imports_atomic(brain, imports)
    assert findings == []

    content = active.read_text()
    assert "t1 — New" in content
    assert "existing" in content


def test_append_imports_atomic_conflict_under_lock(tmp_path):
    """live_task_conflicts is re-checked inside the queue lock: an id that
    landed in active.md after the caller's own pre-check (e.g. a concurrent
    writer) must block the write, not silently duplicate it."""
    brain = tmp_path
    (brain / "tasks").mkdir()
    active = brain / "tasks" / "active.md"
    active.write_text("# Active tasks\n\n- [ ] [P1] t1 — Already there\n      role: developer   mode: solo\n      acceptance: x\n")

    imports = [{"id": "t1", "title": "New", "priority": "P2", "acceptance": "A"}]
    findings = append_imports_atomic(brain, imports)

    assert any(f.code == "task-duplicate-id-at-write" for f in findings)
    content = active.read_text()
    assert content.count("t1") == 1
    assert "New" not in content


def test_append_imports_atomic_uses_taskfile_queue_lock(tmp_path):
    """The write must go through brain_core.taskfile.queue_lock, the same
    mutex every other tasks/active.md writer (add/take/release/block/complete)
    uses — not a separate, federation-only lock. Regression for
    t-2026-08-16-federation-import-writes-activ."""
    from brain_core import taskfile as taskfile_module

    brain = tmp_path
    (brain / "tasks").mkdir()
    active = brain / "tasks" / "active.md"
    active.write_text("# Active tasks\n")

    calls = []
    orig_queue_lock = taskfile_module.queue_lock

    def spy_queue_lock(tasks_dir):
        calls.append(Path(tasks_dir))
        return orig_queue_lock(tasks_dir)

    with patch("brain_federation.plan.taskfile.queue_lock", side_effect=spy_queue_lock):
        imports = [{"id": "t1", "title": "New", "priority": "P2", "acceptance": "A"}]
        findings = append_imports_atomic(brain, imports)

    assert findings == []
    assert calls == [brain / "tasks"]


def test_append_imports_atomic_race_with_taskfile_take(tmp_path):
    """Regression for t-2026-08-16-federation-import-writes-activ.

    Before the fix, append_imports_atomic wrote tasks/active.md under its own
    `.locks/tasks-active` directory lock, independent of
    `taskfile.queue_lock` (`tasks/.taskfile.lock`) that `taskfile.take`
    serializes through. A concurrent take() reading active.md, getting
    preempted before its write, while a federation import ran its full
    read-modify-write in that window, silently lost the imported task once
    take() resumed and clobbered the file with its stale copy — with exit
    code 0 on the import side (reproduced separately; see the ticket).

    Forcing that exact interleaving is no longer possible as a *test* against
    the fixed code without deadlocking it on purpose: both operations now
    contend for the same flock, so pausing one mid-critical-section while the
    other tries to acquire the same lock is exactly the contention the fix
    introduces, not a bug. Instead, this test drives genuine lock contention
    from two background threads — take() pauses while holding the lock, the
    import is started concurrently and must block behind it, and only then is
    take() released — and asserts the queue converges to both changes with
    nothing lost."""
    import threading
    import time as time_module

    from brain_core import taskfile as taskfile_module

    brain = tmp_path
    (brain / "tasks").mkdir()
    active = brain / "tasks" / "active.md"
    active.write_text(
        "# Active tasks\n\n"
        "- [ ] [P1] t-race — Race task\n"
        "      role: developer   mode: solo\n"
        "      acceptance: none\n"
    )

    paused = threading.Event()
    release = threading.Event()
    orig_read = taskfile_module._read

    def paused_read(path):
        text = orig_read(path)
        if path == active and not paused.is_set():
            paused.set()
            release.wait(timeout=5)
        return text

    imports = [
        {
            "id": "t-import",
            "title": "Imported task",
            "priority": "P1",
            "acceptance": "y",
            "role": "developer",
            "mode": "solo",
        }
    ]
    import_findings: list[Finding] = []

    def do_import():
        nonlocal import_findings
        import_findings = append_imports_atomic(brain, imports)

    with patch("brain_core.taskfile._read", side_effect=paused_read):
        take_thread = threading.Thread(
            target=lambda: taskfile_module.take(active, "t-race", "agent-A")
        )
        take_thread.start()
        assert paused.wait(timeout=5), "take() never reached the read pause point"

        import_thread = threading.Thread(target=do_import)
        import_thread.start()
        # Best-effort: give the import thread a chance to actually block on
        # the shared flock (held by take()) rather than racing ahead of it.
        # Not load-bearing for correctness — the assertions below hold
        # regardless of whether contention was actually observed.
        time_module.sleep(0.2)

        release.set()
        take_thread.join(timeout=5)
        import_thread.join(timeout=5)

    assert not take_thread.is_alive() and not import_thread.is_alive()
    assert import_findings == []
    final = active.read_text()
    assert "t-import" in final, "federation import was lost to a concurrent take()"
    assert "[~] [P1] t-race" in final, "concurrent take() transition was lost"
    assert final.count("t-race") == 1
    assert final.count("t-import") == 1


def test_append_imports_atomic_concurrent_stress(tmp_path):
    """Unforced concurrent take()/import pairs, run repeatedly: real threads,
    no monkeypatched pause points, letting the OS-level flock arbitrate
    ordering. Directly exercises the acceptance criterion for
    t-2026-08-16-federation-import-writes-activ — concurrent take + import
    must not lose or duplicate queue lines, under whatever interleaving the
    scheduler actually produces."""
    import threading

    from brain_core import taskfile as taskfile_module

    for i in range(20):
        brain = tmp_path / f"run-{i}"
        (brain / "tasks").mkdir(parents=True)
        active = brain / "tasks" / "active.md"
        active.write_text(
            "# Active tasks\n\n"
            f"- [ ] [P1] t-race-{i} — Race task\n"
            "      role: developer   mode: solo\n"
            "      acceptance: none\n"
        )
        imports = [
            {
                "id": f"t-import-{i}",
                "title": "Imported task",
                "priority": "P1",
                "acceptance": "y",
                "role": "developer",
                "mode": "solo",
            }
        ]
        import_findings: list[Finding] = []

        def do_take(active=active, i=i):
            taskfile_module.take(active, f"t-race-{i}", "agent-A")

        def do_import(brain=brain, imports=imports):
            nonlocal import_findings
            import_findings = append_imports_atomic(brain, imports)

        t1 = threading.Thread(target=do_take)
        t2 = threading.Thread(target=do_import)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not t1.is_alive() and not t2.is_alive(), f"run {i}: thread did not finish"
        assert import_findings == [], f"run {i}: unexpected conflict findings"
        final = active.read_text()
        assert final.count(f"t-race-{i}") == 1, f"run {i}: t-race duplicated or lost"
        assert final.count(f"t-import-{i}") == 1, f"run {i}: t-import duplicated or lost"
        assert f"[~] [P1] t-race-{i}" in final, f"run {i}: take() transition lost"


def test_log_imports(tmp_path):
    brain = tmp_path
    (brain / "wiki").mkdir()
    log = brain / "wiki" / "log.md"

    with patch("brain_federation.plan.node_id", return_value="node-alpha"):
        log_imports(brain, "agent", Path("plan.json"), {"plan_id": "p1"}, [{"id": "t1"}])
    content = log.read_text()
    assert "federation-import-task | t1 | agent | node=node-alpha | plan=p1" in content
    assert "federation-import-summary | import-tasks | agent | node=node-alpha | count=1 plan=p1" in content


def test_log_imports_writes_resolved_node(tmp_path, monkeypatch):
    brain = tmp_path
    (brain / "wiki").mkdir()
    log = brain / "wiki" / "log.md"
    monkeypatch.setenv("BRAIN_NODE_ID", "env-node")

    log_imports(brain, "agent", Path("plan.json"), {"plan_id": "p1"}, [{"id": "t1"}])
    content = log.read_text()
    assert "node=env-node | plan=p1" in content

def test_write_proposal_artifacts(tmp_path):
    brain = tmp_path
    (brain / "wiki").mkdir()
    (brain / "wiki" / "p1.md").write_text("old")
    
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "p1.md").write_text("new")
    
    plan = {
        "plan_id": "p1",
        "wiki_proposals": [
            {"path": "wiki/p1.md", "source": str(repo / "p1.md")}
        ]
    }
    
    proposal_dir, written, findings = write_proposal_artifacts(brain, Path("p.json"), plan, "agent")
    assert len(written) == 1
    assert "wiki/p1.md" in written
    assert (proposal_dir / "wiki" / "p1.md").read_text() == "new"
    assert (proposal_dir / "manifest.json").exists()

# --- Command Handlers ---

def test_cmd_plan(tmp_path):
    args = argparse.Namespace(repo=str(tmp_path), brain=str(tmp_path), out=None, json=False)
    with patch("brain_federation.plan.build_plan", return_value=({"ok": True}, [])):
        with patch("brain_federation.plan.emit") as mock_emit:
            assert cmd_plan(args) == 0
            mock_emit.assert_called_once()

def test_cmd_import_tasks(tmp_path):
    plan_file = tmp_path / "plan.json"
    source_state_val = {"repo_head": "a", "repo_status_sha256": "b", "brain_active_sha256": "c", "brain_done_sha256": "d"}
    plan_file.write_text(json.dumps({
        "schema_version": 1, "mode": "plan",
        "source_state": source_state_val,
        "task_imports": [{"id": "t1", "title": "T", "priority": "P1", "acceptance": "A", "state": "open"}]
    }))
    args = argparse.Namespace(plan=str(plan_file), agent="agent-123", yes=True, json=True, allow_drift=False, allow_stale=False)
    
    with patch("brain_federation.plan.source_state", return_value=source_state_val), \
         patch("brain_federation.plan.acquire_import_lock", return_value=(True, "")), \
         patch("brain_federation.plan.release_import_lock"), \
         patch("brain_federation.plan.live_task_conflicts", return_value=[]), \
         patch("brain_federation.plan.append_imports_atomic", return_value=[]) as mock_append, \
         patch("brain_federation.plan.log_imports") as mock_log:
        assert cmd_import_tasks(args) == 0
        mock_append.assert_called_once()
        mock_log.assert_called_once()


def test_cmd_import_tasks_conflict_at_write_time(tmp_path):
    """append_imports_atomic's re-check under the queue lock can find a
    conflict even after the caller's own live_task_conflicts pre-check
    passed (a concurrent writer landed in between). cmd_import_tasks must
    surface that as a block finding, skip log_imports, and report the task
    as not imported — not silently succeed."""
    plan_file = tmp_path / "plan.json"
    source_state_val = {"repo_head": "a", "repo_status_sha256": "b", "brain_active_sha256": "c", "brain_done_sha256": "d"}
    plan_file.write_text(json.dumps({
        "schema_version": 1, "mode": "plan",
        "source_state": source_state_val,
        "task_imports": [{"id": "t1", "title": "T", "priority": "P1", "acceptance": "A", "state": "open"}]
    }))
    args = argparse.Namespace(plan=str(plan_file), agent="agent-123", yes=True, json=True, allow_drift=False, allow_stale=False)

    conflict_finding = Finding("task-duplicate-id-at-write", "block", "tasks/active.md:1", "task t1 already exists in active.md")
    with patch("brain_federation.plan.source_state", return_value=source_state_val), \
         patch("brain_federation.plan.acquire_import_lock", return_value=(True, "")), \
         patch("brain_federation.plan.release_import_lock"), \
         patch("brain_federation.plan.live_task_conflicts", return_value=[]), \
         patch("brain_federation.plan.append_imports_atomic", return_value=[conflict_finding]), \
         patch("brain_federation.plan.log_imports") as mock_log, \
         patch("brain_federation.plan.emit") as mock_emit:
        rc = cmd_import_tasks(args)

    assert rc != 0
    mock_log.assert_not_called()
    data = mock_emit.call_args[0][0]
    assert data["imported"] == []


def test_cmd_write_wiki_proposals(tmp_path):
    plan_file = tmp_path / "plan.json"
    source_state_val = {"repo_head": "a", "repo_status_sha256": "b", "brain_active_sha256": "c", "brain_done_sha256": "d"}
    plan_file.write_text(json.dumps({
        "schema_version": 1, "mode": "plan",
        "source_state": source_state_val,
        "task_imports": [],
        "wiki_proposals": []
    }))
    args = argparse.Namespace(plan=str(plan_file), agent="agent-123", yes=True, json=True, allow_drift=False, allow_stale=False)
    
    with patch("brain_federation.plan.source_state", return_value=source_state_val), \
         patch("brain_federation.plan.proposal_gate_findings", return_value=[]), \
         patch("brain_federation.plan.write_proposal_artifacts", return_value=(tmp_path/"dir", [], [])):
        assert cmd_write_wiki_proposals(args) == 0
