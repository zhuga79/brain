"""queue-cycle: предложения запусков на подтверждение с дашборда.

Цикл никогда не запускает агентов сам. Он готовит список предложений и, если
очередь к запуску не готова, заводит corrective-задачу.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import brain_launch_queue
import brain_task_parser
from brain_core import atomic, clock, journal

from . import corrective, runner, systemd

try:
    import brain_provider
except Exception:  # pragma: no cover — покрыто смоук-тестами
    brain_provider = None  # type: ignore[assignment]


NAME = "brain-queue-cycle"
DEFAULT_AGENT = "codex-gpt5-queue-cycle"
ALLOWED_CLIENTS = set(brain_launch_queue.ALLOWED_CLIENTS)
PRIO_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def parse_tasks(path: Path) -> list[dict[str, Any]]:
    text = atomic.read_text(path)
    return [brain_task_parser.parse_block(block) for block in brain_task_parser.find_blocks(text)]


def valid_acceptance(task: dict[str, Any]) -> bool:
    acceptance = str(task.get("acceptance") or "").strip()
    return bool(acceptance) and acceptance.upper() != "TODO"


def task_sort_key(task: dict[str, Any]) -> tuple[int, str]:
    return (PRIO_ORDER.get(task.get("prio", "P3"), 9), task.get("id", ""))


def client_from_command(command: str) -> str:
    first = (command or "").strip().split(maxsplit=1)[0] if (command or "").strip() else ""
    return first if first in ALLOWED_CLIENTS else "codex"


def task_field(task: dict[str, Any], name: str) -> str:
    pattern = re.compile(rf"^\s*{re.escape(name)}:\s*(.+?)\s*$", re.M)
    if match := pattern.search(str(task.get("raw") or "")):
        return match.group(1).strip()
    return ""


def task_workspace(brain: Path, task: dict[str, Any]) -> str:
    explicit = task_field(task, "workspace")
    if explicit:
        return str(Path(explicit).expanduser().resolve())
    if (brain / "BRAIN.md").exists():
        return str(brain)
    return ""


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def console_command(brain: Path, *, workspace: str, task_id: str, role: str, client: str) -> str:
    parts = ["brain-orchestrator", "--brain", sh_quote(str(brain)), "console"]
    if workspace:
        parts.extend(["--workspace", sh_quote(workspace)])
    parts.extend(["--task", sh_quote(task_id), "--role", sh_quote(role), "--primary", sh_quote(client)])
    return " ".join(parts)


def provider_for_role(brain: Path, role: str) -> dict[str, str]:
    if brain_provider is not None:
        try:
            roles = brain_provider.collect_provider_status(brain).get("roles", {})
            preferred = (roles.get(role) or {}).get("preferred") or {}
            command = str(preferred.get("command") or "")
            client = client_from_command(command)
            return {
                "client": client,
                "provider": str(preferred.get("provider") or client),
                "model": str(preferred.get("model") or ""),
                "effort": str(preferred.get("effort") or ""),
                "command": command or client,
            }
        except Exception:
            pass
    return {"client": "codex", "provider": "codex", "model": "", "effort": "", "command": "codex"}


def build_proposals(brain: Path, *, limit: int) -> list[dict[str, Any]]:
    active = parse_tasks(brain / "tasks" / "active.md")
    runnable = [
        task for task in active
        if task.get("state") == " "
        and str(task.get("mode") or "solo") == "solo"
        and valid_acceptance(task)
    ]
    stamp = clock.utc_now()
    proposals: list[dict[str, Any]] = []
    for task in sorted(runnable, key=task_sort_key)[:limit]:
        role = str(task.get("role") or "developer")
        provider = provider_for_role(brain, role)
        task_id = str(task["id"])
        workspace = task_workspace(brain, task)
        proposals.append({
            "id": f"qp-{stamp[:10]}-{corrective.slugify(task_id, 58)}",
            "status": "pending",
            "created_at": stamp,
            "scope": "workspace" if workspace else "global",
            "workspace": workspace,
            "task": task_id,
            "title": str(task.get("title") or ""),
            "role": role,
            "priority": str(task.get("prio") or ""),
            "client": provider["client"],
            "provider": provider["provider"],
            "model": provider["model"],
            "effort": provider["effort"],
            "command": console_command(
                brain, workspace=workspace, task_id=task_id, role=role, client=provider["client"]
            ),
            "requires_dashboard_confirm": True,
        })
    return proposals


def correctives(brain: Path, proposals: list[dict[str, Any]], *, low_watermark: int) -> list[str]:
    """Чего очереди не хватает, чтобы её можно было запускать."""
    active = parse_tasks(brain / "tasks" / "active.md")
    pending: list[corrective.Corrective] = []
    if any(task.get("state") == " " and not valid_acceptance(task) for task in active):
        pending.append(corrective.Corrective(
            title="Queue corrective: formalize tasks before launch",
            source="queue-cycle:formalize",
            role="pm",
            priority="P1",
            acceptance=(
                "All open tasks that should be launchable have concrete acceptance criteria "
                "and no acceptance: TODO."
            ),
        ))
    if len(proposals) < low_watermark:
        pending.append(corrective.Corrective(
            title="Queue corrective: decompose next launchable work",
            source="queue-cycle:low-watermark",
            role="product",
            acceptance=(
                "At least two launchable next tasks exist with role, mode, and concrete "
                "acceptance criteria."
            ),
        ))
    return corrective.append(brain, pending)


def write_proposals(brain: Path, proposals: list[dict[str, Any]], added_tasks: list[str], agent: str) -> Path:
    payload = {
        "ok": True,
        "generated_at": clock.utc_now(),
        "agent": agent,
        "summary": {
            "pending": sum(1 for item in proposals if item.get("status") == "pending"),
            "corrective_tasks_added": len(added_tasks),
        },
        "proposals": proposals,
        "corrective_tasks_added": added_tasks,
    }
    path = brain_launch_queue.proposals_path(brain)
    brain_launch_queue.atomic_write_json(path, payload)
    return path


def append_log(brain: Path, agent: str, mode: str, proposals: list[dict[str, Any]], added: list[str], path: Path) -> None:
    rel = path.relative_to(brain) if path.is_relative_to(brain) else path
    journal.append_line(
        f"\n## [{clock.utc_now()}] queue-cycle | {agent} | mode={mode} "
        f"proposals={len(proposals)} tasks_added={len(added)} path={rel}",
        brain,
    )


def load_existing_proposals(brain: Path) -> list[dict[str, Any]]:
    path = brain_launch_queue.proposals_path(brain)
    if not path.exists():
        return []
    try:
        data = json.loads(atomic.read_text(path))
    except Exception:
        return []
    items = data.get("proposals") if isinstance(data, dict) else []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def merge_with_launched(brain: Path, fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Сохранить уже запущенные предложения по ещё открытым задачам.

    Без этого ежедневный --apply возвращал запущенное предложение обратно в
    pending и предлагал запустить задачу второй раз.
    """
    open_ids = {str(task.get("id") or "") for task in parse_tasks(brain / "tasks" / "active.md")}
    preserved = [
        prop for prop in load_existing_proposals(brain)
        if prop.get("status") == "launched" and str(prop.get("task") or "") in open_ids
    ]
    preserved_tasks = {str(prop.get("task") or "") for prop in preserved}
    return preserved + [prop for prop in fresh if str(prop.get("task") or "") not in preserved_tasks]


def run(args: argparse.Namespace) -> int:
    brain = runner.resolve_brain(args)
    if not (brain / "tasks").exists():
        print(f"ERROR: Brain tasks directory not found: {brain / 'tasks'}", file=sys.stderr)
        return 1
    proposals = build_proposals(brain, limit=args.limit)
    added: list[str] = []
    path = brain_launch_queue.proposals_path(brain)
    mode = "dry-run" if args.dry_run else "apply"
    if not args.dry_run:
        with brain_launch_queue.lock(brain):
            proposals = merge_with_launched(brain, proposals)
            path = write_proposals(brain, proposals, [], args.agent)
        added = correctives(brain, proposals, low_watermark=args.low_watermark)
        if added:
            path = write_proposals(brain, proposals, added, args.agent)
        append_log(brain, args.agent, mode, proposals, added, path)
    payload = {
        "ok": True,
        "brain": str(brain),
        "mode": mode,
        "proposals": proposals,
        "proposal_file": str(path),
        "corrective_tasks_added": added,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"queue-cycle: {mode} proposals={len(proposals)} tasks_added={len(added)} file={path}")
    return 0


def unit(args: argparse.Namespace) -> systemd.UnitSpec:
    brain = runner.resolve_brain(args)
    return systemd.UnitSpec(
        name=NAME,
        service_description="Brain daily queue-cycle launch proposal builder",
        timer_description="Prepare Brain launch proposals daily",
        command=systemd.resolve_command(NAME),
        exec_args=["--brain", str(brain), "--apply", "--agent", args.agent],
        timer_options=[("OnCalendar", "daily"), ("Persistent", "true"), ("RandomizedDelaySec", "30min")],
        working_dir=brain,
        environment=runner.service_environment(brain),
    )


def run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=5, help="Сколько предложений записать максимум.")
    parser.add_argument(
        "--low-watermark",
        type=int,
        default=2,
        help="Ниже этого числа предложений завести задачу на декомпозицию.",
    )


SPEC = runner.CycleSpec(
    name=NAME,
    description="Prepare daily dashboard-confirmed launch proposals.",
    install_description="Install the Brain queue-cycle user systemd timer.",
    run=run,
    unit=unit,
    default_agent=DEFAULT_AGENT,
    run_args=run_args,
)
