"""Remote [~] is a lock conflict, not a silent takeover (federation s2).

After git sync, `.locks/` stays local. The only evidence of a remote holder is
a `[~]` row in the synced `tasks/active.md` with `node:` of another node and a
fresh `started:` (within TTL). `brain-lock acquire` must refuse that row;
`brain-federation plan`/`import-tasks` must emit `task-imported-in-progress`
naming the node; downgrade `[~]` → `[ ]` happens only with `--review-downgrade`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from brain_core import taskfile
from brain_core.clock import utc_now
from brain_federation.core import parse_task_file
from brain_federation.plan import (
    cmd_import_tasks,
    plan_task_imports,
)
from brain_federation.remote_lock import remote_lock_conflict


REPO = Path(__file__).resolve().parents[2]
LOCK_BIN = REPO / "runtime" / "bin" / "brain-lock"
LIB = REPO / "runtime" / "lib"
TTL_DEFAULT = 600

NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
FRESH_STARTED = utc_now(NOW)
STALE_STARTED = utc_now(NOW - timedelta(seconds=TTL_DEFAULT + 1))
BOUNDARY_STARTED = utc_now(NOW - timedelta(seconds=TTL_DEFAULT))


def _active_text(
    *,
    state: str = "~",
    task_id: str = "t-fed-lock",
    node: str | None = "node-remote",
    started: str | None = FRESH_STARTED,
    by: str = "agent-remote",
    ttl: int | None = None,
) -> str:
    lines = [
        "# Active tasks",
        "",
        f"- [{state}] [P1] {task_id} — Remote lock fixture",
        "      role: developer   mode: solo",
        "      acceptance: hold the lock",
    ]
    if started:
        lines.append(f"      started: {started}")
    if by:
        lines.append(f"      by: {by}")
    if node:
        lines.append(f"      node: {node}")
    if ttl is not None:
        lines.append(f"      ttl: {ttl}")
    return "\n".join(lines) + "\n"


def _vault(tmp_path: Path, text: str) -> Path:
    (tmp_path / "tasks").mkdir(parents=True, exist_ok=True)
    (tmp_path / "wiki").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tasks" / "active.md").write_text(text, encoding="utf-8")
    (tmp_path / "wiki" / "log.md").write_text("# Log\n", encoding="utf-8")
    return tmp_path


def _conflict(active: Path, **kwargs):
    defaults = {
        "task_id": "t-fed-lock",
        "local_node": "node-local",
        "now": NOW,
        "default_ttl": TTL_DEFAULT,
    }
    defaults.update(kwargs)
    return remote_lock_conflict(active, **defaults)


class TestRemoteLockConflictUnit:
    def test_fresh_other_node_is_a_conflict(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text())
        hit = _conflict(brain / "tasks" / "active.md")
        assert hit is not None
        assert hit.task_id == "t-fed-lock"
        assert hit.node == "node-remote"
        assert hit.by == "agent-remote"
        assert hit.ttl_s == TTL_DEFAULT
        assert hit.age_s == 0

    def test_stale_other_node_is_not_a_conflict(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text(started=STALE_STARTED))
        assert _conflict(brain / "tasks" / "active.md") is None

    def test_age_equal_to_ttl_is_still_fresh(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text(started=BOUNDARY_STARTED))
        hit = _conflict(brain / "tasks" / "active.md")
        assert hit is not None
        assert hit.age_s == TTL_DEFAULT

    def test_same_node_is_not_a_conflict(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text(node="node-local"))
        assert _conflict(brain / "tasks" / "active.md") is None

    def test_legacy_in_progress_without_node_is_not_a_conflict(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text(node=None))
        assert _conflict(brain / "tasks" / "active.md") is None

    def test_open_task_is_not_a_conflict(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text(state=" ", node="node-remote"))
        assert _conflict(brain / "tasks" / "active.md") is None

    def test_missing_file_is_not_a_conflict(self, tmp_path: Path):
        assert _conflict(tmp_path / "nope" / "active.md") is None

    def test_empty_file_is_not_a_conflict(self, tmp_path: Path):
        path = tmp_path / "active.md"
        path.write_text("", encoding="utf-8")
        assert _conflict(path) is None

    def test_unknown_task_id_is_not_a_conflict(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text())
        assert _conflict(brain / "tasks" / "active.md", task_id="t-other") is None

    def test_missing_started_on_other_node_is_treated_fresh(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text(started=None))
        hit = _conflict(brain / "tasks" / "active.md")
        assert hit is not None
        assert hit.node == "node-remote"

    def test_unparseable_started_is_treated_fresh(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text(started="not-a-timestamp"))
        assert _conflict(brain / "tasks" / "active.md") is not None

    def test_task_ttl_overrides_default(self, tmp_path: Path):
        started = utc_now(NOW - timedelta(seconds=90))
        brain = _vault(tmp_path, _active_text(started=started, ttl=60))
        assert _conflict(brain / "tasks" / "active.md") is None
        brain2 = _vault(tmp_path / "fresh", _active_text(started=started, ttl=120))
        hit = _conflict(brain2 / "tasks" / "active.md")
        assert hit is not None
        assert hit.ttl_s == 120

    def test_none_task_id_is_not_a_conflict(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text())
        assert remote_lock_conflict(
            brain / "tasks" / "active.md",
            task_id="",
            local_node="node-local",
            now=NOW,
        ) is None

    def test_email_node_charset_is_accepted(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text(node="alice+tag@example.org"))
        hit = _conflict(brain / "tasks" / "active.md")
        assert hit is not None
        assert hit.node == "alice+tag@example.org"


def _lock_env(brain: Path, node: str = "node-local") -> dict[str, str]:
    env = os.environ.copy()
    env["BRAIN_PATH"] = str(brain)
    env["BRAIN_NODE_ID"] = node
    env["BRAIN_SKIP_OPERATOR_ENV"] = "1"
    env["PYTHONPATH"] = str(LIB)
    return env


def _acquire(brain: Path, task_id: str = "t-fed-lock", extra: list[str] | None = None, **env_kw):
    cmd = [str(LOCK_BIN), "acquire", task_id, "--as", "agent-local", "--json"]
    if extra:
        cmd.extend(extra)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=_lock_env(brain, **env_kw),
        check=False,
    )


class TestBrainLockAcquireCli:
    def test_acquire_refuses_fresh_remote_in_progress(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text(started=utc_now()))
        proc = _acquire(brain)
        assert proc.returncode == 1, proc.stdout + proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["ok"] is False
        assert payload.get("node") == "node-remote"
        assert "node-remote" in (proc.stdout + proc.stderr)

    def test_acquire_allows_stale_remote_in_progress(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text(started=STALE_STARTED))
        proc = _acquire(brain)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["ok"] is True

    def test_acquire_allows_same_node(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text(node="node-local", started=utc_now()))
        proc = _acquire(brain)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_acquire_allows_open_task(self, tmp_path: Path):
        brain = _vault(tmp_path, _active_text(state=" ", node=None, started=None, by=""))
        proc = _acquire(brain)
        assert proc.returncode == 0, proc.stdout + proc.stderr


class TestImportedInProgressFinding:
    def test_parse_names_the_remote_node(self, tmp_path: Path):
        path = tmp_path / "active.md"
        path.write_text(_active_text(), encoding="utf-8")
        _tasks, findings = parse_task_file(path, "repo-active")
        codes = [f.code for f in findings]
        assert "task-imported-in-progress" in codes
        block = next(f for f in findings if f.code == "task-imported-in-progress")
        assert block.severity == "block"
        assert "node-remote" in block.message
        assert "t-fed-lock" in block.message

    def test_parse_without_node_still_blocks(self, tmp_path: Path):
        path = tmp_path / "active.md"
        path.write_text(_active_text(node=None), encoding="utf-8")
        _tasks, findings = parse_task_file(path, "repo-active")
        block = next(f for f in findings if f.code == "task-imported-in-progress")
        assert block.severity == "block"

    def test_plan_blocks_remote_in_progress_and_does_not_import(self, tmp_path: Path):
        repo = tmp_path / "repo"
        brain = tmp_path / "brain"
        (repo / "tasks").mkdir(parents=True)
        (brain / "tasks").mkdir(parents=True)
        (repo / "tasks" / "active.md").write_text(_active_text(), encoding="utf-8")
        (brain / "tasks" / "active.md").write_text("# Active\n", encoding="utf-8")
        (brain / "tasks" / "done.md").write_text("# Done\n", encoding="utf-8")

        imports, skipped, findings = plan_task_imports(repo, brain)
        assert imports == []
        assert any(item["id"] == "t-fed-lock" for item in skipped)
        block = next(f for f in findings if f.code == "task-imported-in-progress")
        assert block.severity == "block"
        assert "node-remote" in block.message

    def test_plan_does_not_downgrade_without_flag(self, tmp_path: Path):
        repo = tmp_path / "repo"
        brain = tmp_path / "brain"
        (repo / "tasks").mkdir(parents=True)
        (brain / "tasks").mkdir(parents=True)
        (repo / "tasks" / "active.md").write_text(_active_text(), encoding="utf-8")
        (brain / "tasks" / "active.md").write_text("# Active\n", encoding="utf-8")
        (brain / "tasks" / "done.md").write_text("# Done\n", encoding="utf-8")

        imports, _skipped, findings = plan_task_imports(repo, brain)
        assert all(item.get("state") != "open" or item["id"] != "t-fed-lock" for item in imports)
        assert any(f.code == "task-imported-in-progress" and f.severity == "block" for f in findings)

    def test_plan_review_downgrade_imports_as_open(self, tmp_path: Path):
        repo = tmp_path / "repo"
        brain = tmp_path / "brain"
        (repo / "tasks").mkdir(parents=True)
        (brain / "tasks").mkdir(parents=True)
        (repo / "tasks" / "active.md").write_text(_active_text(), encoding="utf-8")
        (brain / "tasks" / "active.md").write_text("# Active\n", encoding="utf-8")
        (brain / "tasks" / "done.md").write_text("# Done\n", encoding="utf-8")

        imports, _skipped, findings = plan_task_imports(repo, brain, review_downgrade=True)
        assert len(imports) == 1
        assert imports[0]["id"] == "t-fed-lock"
        assert imports[0]["state"] == "open"
        assert not any(f.code == "task-imported-in-progress" and f.severity == "block" for f in findings)
        review = next(f for f in findings if f.code == "task-imported-in-progress")
        assert review.severity == "review"
        assert "node-remote" in review.message

    def test_import_tasks_refuses_plan_block_without_flag(self, tmp_path: Path, capsys):
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "mode": "plan",
                    "repo": str(tmp_path),
                    "brain": str(tmp_path),
                    "source_state": {
                        "repo_head": "a",
                        "repo_status_sha256": "b",
                        "brain_active_sha256": "c",
                        "brain_done_sha256": "d",
                    },
                    "summary": {"block": 1, "review": 0, "warn": 0, "info": 0},
                    "findings": [
                        {
                            "code": "task-imported-in-progress",
                            "severity": "block",
                            "path": "tasks/active.md:3",
                            "message": "task t-fed-lock is imported as in-progress on node node-remote",
                        }
                    ],
                    "task_imports": [],
                    "skipped_tasks": [
                        {
                            "id": "t-fed-lock",
                            "title": "Remote lock fixture",
                            "priority": "P1",
                            "role": "developer",
                            "mode": "solo",
                            "acceptance": "hold the lock",
                            "reason": "state-~",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        args = type(
            "Args",
            (),
            {
                "plan": str(plan_file),
                "agent": "agent-123",
                "yes": False,
                "json": True,
                "allow_drift": False,
                "allow_stale": False,
                "review_downgrade": False,
            },
        )()
        rc = cmd_import_tasks(args)
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        codes = {f["code"] for f in data["findings"]}
        assert "plan-block-findings" in codes
        assert data["imported"] == []
        assert data["would_import"] == 0

    def test_import_tasks_review_downgrade_promotes_in_progress(self, tmp_path: Path, capsys):
        (tmp_path / "tasks").mkdir()
        (tmp_path / "tasks" / "active.md").write_text("# Active\n", encoding="utf-8")
        (tmp_path / "tasks" / "done.md").write_text("# Done\n", encoding="utf-8")
        plan_file = tmp_path / "plan.json"
        fingerprints = {
            "repo_head": "a",
            "repo_status_sha256": "b",
            "brain_active_sha256": "c",
            "brain_done_sha256": "d",
        }
        plan_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "mode": "plan",
                    "repo": str(tmp_path),
                    "brain": str(tmp_path),
                    "source_state": fingerprints,
                    "summary": {"block": 1, "review": 0, "warn": 0, "info": 0},
                    "findings": [
                        {
                            "code": "task-imported-in-progress",
                            "severity": "block",
                            "path": "tasks/active.md:3",
                            "message": "task t-fed-lock is imported as in-progress on node node-remote",
                        }
                    ],
                    "task_imports": [],
                    "skipped_tasks": [
                        {
                            "id": "t-fed-lock",
                            "title": "Remote lock fixture",
                            "priority": "P1",
                            "role": "developer",
                            "mode": "solo",
                            "acceptance": "hold the lock",
                            "reason": "state-~",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        args = type(
            "Args",
            (),
            {
                "plan": str(plan_file),
                "agent": "agent-123",
                "yes": False,
                "json": True,
                "allow_drift": True,
                "allow_stale": True,
                "review_downgrade": True,
            },
        )()
        rc = cmd_import_tasks(args)
        captured = capsys.readouterr().out
        data = json.loads(captured)
        assert rc == 0, data
        assert data["would_import"] == 1
        codes = {f["code"] for f in data["findings"]}
        assert "plan-block-findings" not in codes


class TestTakeWritesNode:
    def test_take_records_node_and_ttl(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BRAIN_NODE_ID", "node-alpha")
        brain = _vault(tmp_path, _active_text(state=" ", node=None, started=None, by=""))
        active = brain / "tasks" / "active.md"
        taskfile.take(active, "t-fed-lock", "agent-local", ttl=120)
        text = active.read_text(encoding="utf-8")
        assert "node: node-alpha" in text
        assert "ttl: 120" in text
        assert "- [~] [P1] t-fed-lock" in text

    def test_release_strips_node_and_ttl(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BRAIN_NODE_ID", "node-alpha")
        brain = _vault(tmp_path, _active_text(state=" ", node=None, started=None, by=""))
        active = brain / "tasks" / "active.md"
        taskfile.take(active, "t-fed-lock", "agent-local")
        taskfile.release(active, "t-fed-lock", "agent-local")
        text = active.read_text(encoding="utf-8")
        assert "node:" not in text
        assert "ttl:" not in text
        assert "by:" not in text
        assert "- [ ] [P1] t-fed-lock" in text
