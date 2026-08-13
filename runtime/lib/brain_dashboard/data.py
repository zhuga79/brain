"""Точка входа сбора данных для дашборда.

Здесь остались только агрегаторы — те, что собирают картину из всех предметных
модулей `brain_dashboard.collect`. Сами сборщики лежат там; имена
реэкспортируются, чтобы внешние вызывающие не правились при перестановке.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import brain_provider
from brain_app import queue

from . import schedule
from .collect.council import read_council
from .collect.handoff import collect_handoff_status, collect_operator_status, read_handoff_journal
from .collect.knowledge import (
    collect_wiki,
    read_audit_log,
    read_graph,
    read_index,
    read_obsidian_views,
)
from .collect.learning import collect_learning_stats, collect_token_metrics
from .collect.snapshot import compute_delta, load_snapshot, save_snapshot
from .collect.tasks import (
    brain_path,
    read_locks,
    summarize_tasks,
)
from .collect.workspaces import collect_queue_proposals, collect_workspaces

__all__ = [
    "brain_path", "summarize_tasks",
    "read_locks", "read_council", "read_index", "read_graph", "read_audit_log",
    "read_obsidian_views", "collect_wiki", "read_handoff_journal", "collect_handoff_status",
    "collect_operator_status", "collect_learning_stats", "collect_token_metrics",
    "collect_queue_proposals", "collect_workspaces", "collect_scheduled_jobs",
    "collect_status", "collect_metrics", "load_snapshot", "save_snapshot", "compute_delta",
]


def _state_signature(status: dict[str, Any]) -> str:
    """Content hash of the meaningful, user-visible state. Changes only when
    tasks, locks, launch proposals or workspace next-tasks actually change —
    used by the dashboard to auto-refresh only on real changes."""
    parts: list[str] = []
    tasks = status.get("tasks", {}) if isinstance(status, dict) else {}
    for t in (tasks.get("active") or []):
        parts.append(f"{t.get('id')}:{t.get('state')}:{t.get('prio') or t.get('priority')}")
    parts.append("done=" + str(len(tasks.get("done") or [])))
    parts.append("locks=" + str((status.get("locks") or {}).get("count")))
    for prop in ((status.get("queue_autopilot") or {}).get("proposals") or []):
        parts.append(f"qp:{prop.get('id')}:{prop.get('status')}")
    ws = status.get("workspaces") or {}
    for w in (ws.get("items") or ws.get("workspaces") or []):
        nt = w.get("next_task") or {}
        parts.append(f"ws:{w.get('path')}:{nt.get('task_id')}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def collect_status(brain: Path) -> dict[str, Any]:
    active = queue.load_active(brain)
    done = queue.load_done(brain)
    locks = read_locks(brain)
    councils = read_council(brain)
    status = {
        "brain": str(brain),
        "tasks": {
            "summary": summarize_tasks(active, done),
            "active": active,
            "done": done,
        },
        "locks": {
            "count": len(locks),
            "stale_count": sum(1 for lock in locks if lock.get("stale") is True),
            "items": locks,
        },
        "council": {"count": len(councils), "items": councils},
        "index": read_index(brain),
        "learning": collect_learning_stats(brain),
        "providers": brain_provider.collect_provider_status(brain),
        "tokens": collect_token_metrics(brain),
        "handoff": collect_handoff_status(brain),
        "operator": collect_operator_status(brain),
        "handoff_journal": read_handoff_journal(brain),
        "graph": read_graph(brain),
        "obsidian_views": read_obsidian_views(brain),
        "wiki": collect_wiki(brain),
        "scheduled": collect_scheduled_jobs(),
        "workspaces": collect_workspaces(),
        "queue_autopilot": collect_queue_proposals(brain),
    }
    status["signature"] = _state_signature(status)
    return status


def collect_scheduled_jobs() -> dict[str, Any]:
    """Расписания cron/systemd/at. Опрос и разбор — в brain_dashboard.schedule."""
    return schedule.collect()


def collect_metrics(brain: Path) -> dict[str, Any]:
    """Return flat counter metrics for orchestration/learning/webhook/policy."""
    status = collect_status(brain)
    task_sum = status["tasks"]["summary"]  # dict with active_count / done_count keys

    ls = status.get("learning", {})
    lc = ls.get("counts", {})
    token_metrics = status.get("tokens", {}).get("aggregate", {})

    dead_letter = brain / ".webhooks" / "dead-letter.jsonl"
    dl_count = 0
    if dead_letter.exists():
        try:
            dl_count = sum(1 for l in dead_letter.read_text().splitlines() if l.strip())
        except OSError:
            pass

    # Policy metrics from .policy/last-check.json (written by brain-policy check)
    policy_block: dict[str, Any] = {"status": "unchecked"}
    policy_file = brain / ".policy" / "last-check.json"
    if policy_file.exists():
        try:
            data = json.loads(policy_file.read_text(encoding="utf-8"))
            last_run = data.get("last_run", "")
            age_seconds: int | None = None
            if last_run:
                try:
                    ts = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                    age_seconds = int(
                        (datetime.now(timezone.utc) - ts).total_seconds())
                except ValueError:
                    pass
            policy_block = {
                "status": "ok" if data.get("ok") else "failed",
                "last_run": last_run,
                "age_seconds": age_seconds,
                "gates_passed": data.get("gates_passed", 0),
                "gates_failed": data.get("gates_failed", 0),
            }
        except (OSError, json.JSONDecodeError):
            policy_block = {"status": "error"}

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "orchestration": {
            "tasks_active": task_sum.get("active_count", 0),
            "tasks_done": task_sum.get("done_count", 0),
            "locks_active": status["locks"]["count"],
            "locks_stale": status["locks"]["stale_count"],
            "councils_active": status["council"]["count"],
        },
        "learning": {
            "incidents": lc.get("incidents", 0),
            "lessons_pending": lc.get("pending", 0),
            "lessons_approved": lc.get("approved", 0),
            "lessons_active": lc.get("active", 0),
            "lessons_deprecated": lc.get("deprecated", 0),
        },
        "webhook": {
            "dead_letter_count": dl_count,
        },
        "policy": policy_block,
        "token_economy": token_metrics,
    }
