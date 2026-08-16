"""review-cycle: детерминированный обзор состояния очереди и репозитория.

Цикл намеренно не запускает LLM-агентов. Он считает измеримое — задачи без
критерия готовности, разросшийся файл, серию правок одного модуля — пишет отчёт
и заводит corrective-задачи под подходящую роль.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import brain_task_parser
from brain_core import atomic, clock, journal

from . import corrective, runner, systemd

NAME = "brain-review-cycle"
DEFAULT_AGENT = "codex-gpt5-review-cycle"
DEFAULT_ROLE = "reviewer"


def parse_tasks(path: Path) -> list[dict[str, Any]]:
    text = atomic.read_text(path)
    return [brain_task_parser.parse_block(block) for block in brain_task_parser.find_blocks(text)]


def git_output(brain: Path, args: list[str]) -> str:
    if not (brain / ".git").exists():
        return ""
    result = subprocess.run(
        ["git", "-C", str(brain), *args], check=False, capture_output=True, text=True, timeout=5
    )
    return result.stdout if result.returncode == 0 else ""


def count_lines(path: Path) -> int:
    return len(atomic.read_text(path).splitlines()) if path.exists() else 0


def corrective_task(issue_id: str, title: str, role: str, priority: str, acceptance: str) -> dict[str, str]:
    return {
        "issue_id": issue_id,
        "title": title,
        "role": role,
        "priority": priority,
        "acceptance": acceptance,
    }


def analyze(brain: Path) -> list[dict[str, Any]]:
    active = parse_tasks(brain / "tasks" / "active.md")
    open_tasks = [task for task in active if task.get("state") in {" ", "~", "!"}]
    issues: list[dict[str, Any]] = []

    missing_acceptance = [
        task for task in open_tasks
        if not task.get("acceptance") or task.get("acceptance", "").strip().upper() == "TODO"
    ]
    if missing_acceptance:
        task_ids = ", ".join(task["id"] for task in missing_acceptance[:8])
        if len(missing_acceptance) > 8:
            task_ids += f" +{len(missing_acceptance) - 8}"
        issues.append({
            "id": "acceptance-todo",
            "severity": "critical",
            "summary": f"{len(missing_acceptance)} active task(s) have empty or TODO acceptance",
            "evidence": task_ids,
            "recommendation": "Repair acceptance before implementation starts or resumes.",
            "corrective": corrective_task(
                "acceptance-todo",
                "Review corrective: replace TODO acceptance criteria",
                "pm",
                "P1",
                "Active tasks listed in the linked review have concrete acceptance criteria and no active task keeps acceptance: TODO.",
            ),
        })

    p1_active = [task for task in open_tasks if task.get("prio") == "P1"]
    if len(p1_active) > 1:
        issues.append({
            "id": "p1-wip-limit",
            "severity": "concern",
            "summary": f"{len(p1_active)} active P1 task(s) are open at once",
            "evidence": ", ".join(task["id"] for task in p1_active[:8]),
            "recommendation": "Limit active P1 work to the next outcome-bearing item.",
            "corrective": corrective_task(
                "p1-wip-limit",
                "Review corrective: reduce active P1 WIP",
                "delivery",
                "P2",
                "Active P1 list is triaged to one primary developer P1 and explicit deferred/backlog status for the rest.",
            ),
        })

    dashboard_lines = count_lines(brain / "runtime" / "lib" / "brain_dashboard" / "render" / "html.py")
    if dashboard_lines >= 1400:
        issues.append({
            "id": "dashboard-render-size",
            "severity": "concern",
            "summary": f"Dashboard HTML renderer is {dashboard_lines} lines",
            "evidence": "runtime/lib/brain_dashboard/render/html.py",
            "recommendation": "Split search/actions/scheduled/task-tree rendering into testable modules after current P1 stabilization.",
            "corrective": corrective_task(
                "dashboard-render-size",
                "Review corrective: split dashboard renderer boundaries",
                "architect",
                "P2",
                "A scoped refactor plan exists for dashboard render modules with no new UI features added in the same task.",
            ),
        })

    dashboard_commits = git_output(brain, [
        "log", "--since=3 days ago", "--oneline", "--",
        "runtime/bin/brain-dashboard",
        "runtime/lib/brain_dashboard",
        "tests/python/test_brain_dashboard_data.py",
        "tests/python/test_brain_dashboard_render.py",
        "tests/cases/09-dashboard.sh",
        "tests/cases/11-dashboard-post.sh",
    ]).strip().splitlines()
    if len(dashboard_commits) >= 5:
        issues.append({
            "id": "dashboard-reactive-loop",
            "severity": "concern",
            "summary": f"{len(dashboard_commits)} dashboard-related commits in the last 3 days",
            "evidence": "; ".join(dashboard_commits[:5]),
            "recommendation": "Run a stabilization checkpoint before adding more dashboard surface area.",
            "corrective": corrective_task(
                "dashboard-reactive-loop",
                "Review corrective: dashboard stabilization checkpoint",
                "reviewer",
                "P1",
                "Dashboard happy path is reviewed end-to-end; failures are grouped by root cause; new feature work is gated until P1 stability criteria are literal.",
            ),
        })

    return issues


def report_path(brain: Path, ts: dt.datetime) -> Path:
    return brain / "wiki" / f"review-cycle-{clock.stamp_for_filename(ts)}.md"


def render_report(
    brain: Path, ts: dt.datetime, role: str, agent: str, mode: str,
    issues: list[dict[str, Any]], added: list[str],
) -> str:
    day = ts.strftime("%Y-%m-%d")
    lines = [
        "---",
        f"title: Review Cycle {ts.strftime('%Y-%m-%d %H:%M UTC')}",
        "type: concept",
        f"created: {day}",
        f"updated: {day}",
        "curation: agent",
        "source_policy: ignored",
        "tags: [review-cycle]",
        "---",
        "",
        f"# Review Cycle {clock.utc_now(ts)}",
        "",
        f"- role: {role}",
        f"- agent: {agent}",
        f"- mode: {mode}",
        f"- brain: {brain}",
        f"- issues: {len(issues)}",
        f"- corrective_tasks_added: {len(added)}",
        "",
        "## Findings",
        "",
    ]
    if not issues:
        lines.extend(["No issues found.", ""])
    for issue in issues:
        lines.extend([
            f"### {issue['severity'].upper()} {issue['id']}",
            "",
            f"- summary: {issue['summary']}",
            f"- evidence: {issue['evidence']}",
            f"- recommendation: {issue['recommendation']}",
            "",
        ])
    lines.extend(["## Corrective Tasks", ""])
    lines.extend([f"- added: {task_id}" for task_id in added] or ["- added: none"])
    lines.append("")
    return "\n".join(lines)


def render_registry(ts: dt.datetime, body: str = "") -> str:
    today = ts.strftime("%Y-%m-%d")
    return "\n".join([
        "---",
        "title: Review Cycles",
        "type: concept",
        f"created: {today}",
        f"updated: {today}",
        "curation: agent",
        "source_policy: ignored",
        "tags: [review-cycle]",
        "---",
        "",
        "# Review Cycles",
        "",
        body.strip(),
        "",
    ]).rstrip() + "\n"


def ensure_review_registry(
    brain: Path, report: Path, ts: dt.datetime, mode: str,
    issues: list[dict[str, Any]], added: list[str],
) -> None:
    registry = brain / "wiki" / "review-cycles.md"
    entry = f"- {clock.utc_now(ts)} - [[{report.stem}]] - mode={mode} issues={len(issues)} added={len(added)}"
    if registry.exists():
        text = atomic.read_text(registry)
        text = re.sub(r"^updated:\s*.+$", f"updated: {ts.strftime('%Y-%m-%d')}", text, count=1, flags=re.M)
        if f"[[{report.stem}]]" not in text:
            text = text.rstrip() + "\n" + entry + "\n"
    else:
        text = render_registry(ts, entry)
    atomic.write_text(registry, text)

    index = brain / "wiki" / "index.md"
    index_text = atomic.read_text(index) or "# Wiki Index\n"
    if "[[review-cycles]]" not in index_text:
        atomic.write_text(index, index_text.rstrip() + "\n\n## Automation\n- [[review-cycles]]\n")


def append_corrective_tasks(brain: Path, issues: list[dict[str, Any]], report: Path, ts: dt.datetime) -> list[str]:
    report_ref = str(report.relative_to(brain))
    items = []
    for issue in issues:
        spec = issue.get("corrective") or {}
        if not spec.get("title"):
            continue
        items.append(corrective.Corrective(
            title=spec["title"],
            source=f"review-cycle:{spec.get('issue_id', issue['id'])}",
            role=spec.get("role", "developer"),
            priority=spec.get("priority", "P2"),
            acceptance=spec.get("acceptance", corrective.DEFAULT_ACCEPTANCE),
            ref=report_ref,
        ))
    return corrective.append(brain, items, day=ts.strftime("%Y-%m-%d"))


def append_log(brain: Path, ts: dt.datetime, agent: str, role: str, mode: str, report: Path, added: list[str]) -> None:
    rel = report.relative_to(brain) if report.is_relative_to(brain) else report
    journal.append_line(
        f"\n## [{clock.utc_now(ts)}] review-cycle | {agent} | role={role} mode={mode} "
        f"report={rel} tasks_added={len(added)}",
        brain,
    )


def run(args: argparse.Namespace) -> int:
    brain = runner.resolve_brain(args)
    if not (brain / "tasks").exists():
        print(f"ERROR: Brain tasks directory not found: {brain / 'tasks'}", file=sys.stderr)
        return 1

    ts = clock.now()
    mode = "dry-run" if args.dry_run else "apply"
    issues = analyze(brain)
    report = report_path(brain, ts)
    added = [] if args.dry_run else append_corrective_tasks(brain, issues, report, ts)
    atomic.write_text(report, render_report(brain, ts, args.role, args.agent, mode, issues, added))
    ensure_review_registry(brain, report, ts, mode, issues, added)
    append_log(brain, ts, args.agent, args.role, mode, report, added)

    payload = {
        "brain": str(brain),
        "mode": mode,
        "role": args.role,
        "agent": args.agent,
        "report": str(report),
        "issues": issues,
        "tasks_added": added,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"review-cycle: {mode} issues={len(issues)} added={len(added)} report={report}")
    return 0


def unit(args: argparse.Namespace) -> systemd.UnitSpec:
    brain = runner.resolve_brain(args)
    return systemd.UnitSpec(
        name=NAME,
        service_description="Brain recurring reviewer cycle",
        timer_description="Run Brain reviewer cycle every 3 days",
        command=systemd.resolve_command(NAME),
        exec_args=["--brain", str(brain), "--apply", "--role", args.role, "--agent", args.agent],
        timer_options=[
            ("OnBootSec", "15min"),
            ("OnUnitActiveSec", "3d"),
            ("AccuracySec", "1h"),
            ("Persistent", "true"),
        ],
        working_dir=brain,
        environment=runner.service_environment(brain),
    )


def role_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--role", default=DEFAULT_ROLE, help="Роль, записываемая в отчёт ревью.")


SPEC = runner.CycleSpec(
    name=NAME,
    description="Run the Brain recurring review cycle.",
    install_description="Install the Brain review cycle user systemd timer.",
    run=run,
    unit=unit,
    default_agent=DEFAULT_AGENT,
    run_args=role_arg,
    install_args=role_arg,
)
