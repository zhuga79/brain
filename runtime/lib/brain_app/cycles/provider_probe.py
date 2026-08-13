"""provider-probe: проверка доступности провайдеров, закреплённых за ролями.

Роль без живого провайдера — это очередь, которая не запустится, и узнать об
этом лучше от таймера, чем в момент запуска задачи.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from brain_core import clock, journal

from . import corrective, runner, systemd

NAME = "brain-provider-probe"
DEFAULT_AGENT = "provider-probe:cycle"
SOURCE = "provider-probe:down"
TITLE_LIMIT = 70


def append_log(brain: Path, entry: str) -> None:
    journal.append_line(f"- {clock.utc_now()}: {entry}", brain)


def corrective_title(down: dict[str, dict[str, str]]) -> str:
    summary = "; ".join(f"{role} preferred: {info['key']} ({info['status']})" for role, info in down.items())
    if not summary:
        return "Fix brain-provider down status"
    if len(summary) > TITLE_LIMIT:
        summary = summary[: TITLE_LIMIT - 3] + "..."
    return f"Fix down providers: {summary}"


def append_corrective_task(brain: Path, down: dict[str, dict[str, str]]) -> tuple[bool, str]:
    item = corrective.Corrective(
        title=corrective_title(down),
        source=SOURCE,
        role="pm",
        priority="P1",
        slug="provider-down-fix",
        acceptance=(
            "the down provider/CLI is restored or the role repointed; brain-provider status "
            "shows no preferred.status == error."
        ),
    )
    added = corrective.append(brain, [item])
    if not added:
        return False, f"Corrective task with source '{SOURCE}' already exists. Skipping."
    return True, f"Appended corrective task {added[0]} (source '{SOURCE}')."


def get_down_providers(brain: Path) -> tuple[dict[str, dict[str, str]], str | None]:
    """Роли, чей предпочтительный провайдер отвечает ошибкой."""
    proc = None
    try:
        proc = subprocess.run(
            ["brain-provider", "status", "--json"], cwd=str(brain),
            capture_output=True, text=True, timeout=30, check=False,
        )
        if proc.returncode != 0:
            sys.stderr.write(f"Error running 'brain-provider status': {proc.stderr.strip()}\n")
            return {}, f"Command failed: {proc.stderr.strip()}\n"

        status_data = json.loads(proc.stdout)
        down: dict[str, dict[str, str]] = {}
        for role, info in status_data.get("roles", {}).items():
            preferred = info.get("preferred")
            if preferred and preferred.get("status") == "error":
                down[role] = {
                    "key": preferred.get("key", "unknown/unknown"),
                    "status": preferred.get("status", "error"),
                }
        return down, None
    except FileNotFoundError:
        return {}, "'brain-provider' command not found.\n"
    except subprocess.TimeoutExpired:
        return {}, "'brain-provider status' command timed out.\n"
    except json.JSONDecodeError:
        stdout = proc.stdout.strip() if proc else ""
        return {}, f"Failed to parse JSON from 'brain-provider status': {stdout}\n"
    except Exception as exc:  # pragma: no cover — сеть отказов шире, чем перечисленные
        return {}, f"An unexpected error occurred: {exc}\n"


def refresh_health_cache(brain: Path, result: dict[str, Any]) -> str | None:
    """Обновить кеш здоровья провайдеров. Возвращает описание отказа, если он был."""
    try:
        proc = subprocess.run(
            ["brain-provider", "probe", "--json", "--ttl-sec", "90"], cwd=str(brain),
            capture_output=True, text=True, timeout=90, check=False,
        )
        if proc.returncode == 0:
            return None
        message = f"Error running 'brain-provider probe': {proc.stderr.strip()}"
        result["probe_error"] = message
        result["probe_stdout"] = proc.stdout.strip()
        result["probe_stderr"] = proc.stderr.strip()
        return message
    except FileNotFoundError:
        return "'brain-provider' command not found for probe."
    except subprocess.TimeoutExpired:
        return "'brain-provider probe' command timed out."
    except Exception as exc:  # pragma: no cover — сеть отказов шире, чем перечисленные
        return f"An unexpected error occurred during probe: {exc}"


def run_cycle(brain: Path, *, dry_run: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"mode": "dry-run" if dry_run else "apply"}
    error_message = None
    if not dry_run:
        error_message = refresh_health_cache(brain, result)
        if error_message:
            sys.stderr.write(f"{error_message}\n")

    down, status_error = get_down_providers(brain)
    if status_error:
        status_error = status_error.strip()
        error_message = f"{error_message}; {status_error}" if error_message else status_error
        sys.stderr.write(f"Error getting provider status: {status_error}\n")
        result["status_error"] = status_error

    if error_message:
        result["status"] = "error"
        result["message"] = error_message
        result["exit_code"] = 1
        return result

    if down:
        result["status"] = "failure"
        result["message"] = f"Found {len(down)} down providers."
        result["down_providers"] = down
        if dry_run:
            result["action"] = "report"
        else:
            created, message = append_corrective_task(brain, down)
            result["task_created"] = created
            result["task_message"] = message
            append_log(brain, f"provider-probe: FAILED - {message} ({len(down)} down)")
    else:
        result["status"] = "success"
        result["message"] = "All providers healthy."
        if not dry_run:
            append_log(brain, "provider-probe: OK - All providers healthy.")

    result["exit_code"] = 1 if down else 0
    return result


def run(args: argparse.Namespace) -> int:
    brain = runner.resolve_brain(args)
    if not brain.is_dir():
        sys.stderr.write(f"Error: Brain path not found at '{brain}'. Is BRAIN_PATH set correctly?\n")
        return 1

    result = run_cycle(brain, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Status: {result.get('status', 'unknown')}")
        print(f"Message: {result.get('message', 'N/A')}")
        if result.get("down_providers"):
            print("Down Providers:")
            for role, info in result["down_providers"].items():
                print(f"  - {role}: {info['key']} ({info['status']})")
        for label, key in (
            ("Task", "task_message"),
            ("Probe Error", "probe_error"),
            ("Status Error", "status_error"),
        ):
            if result.get(key):
                print(f"{label}: {result[key]}")
        for label, key in (("Probe Stdout", "probe_stdout"), ("Probe Stderr", "probe_stderr")):
            if result.get(key):
                print(f"\n--- {label} ---")
                print(result[key])
                print("--------------------")
    return int(result.get("exit_code", 1))


def unit(args: argparse.Namespace) -> systemd.UnitSpec:
    brain = runner.resolve_brain(args)
    return systemd.UnitSpec(
        name=NAME,
        service_description="Probe brain providers and create corrective task",
        timer_description="Run brain-provider-probe hourly",
        command=systemd.resolve_command(NAME),
        exec_args=["--brain", str(brain), "--apply"],
        timer_options=[("OnCalendar", "hourly"), ("RandomizedDelaySec", "30m"), ("Persistent", "true")],
        unit_options=[("Wants", f"{NAME}.timer")],
        working_dir=brain,
        environment=[("BRAIN_PATH", str(brain))],
    )


SPEC = runner.CycleSpec(
    name=NAME,
    description="Probes brain providers and creates a corrective task if any preferred provider is down.",
    install_description="Install the brain-provider-probe user systemd timer.",
    run=run,
    unit=unit,
    default_agent=DEFAULT_AGENT,
    mode_required=True,
)
