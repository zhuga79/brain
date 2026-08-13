"""validate-cycle: прогон brain-validate с corrective-задачей на провал.

Цикл не чинит структуру сам. Он фиксирует, что валидатор красный, и заводит
одну задачу под linter — ровно одну, сколько бы раз таймер ни сработал до того,
как её закроют.
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

NAME = "brain-validate-cycle"
DEFAULT_AGENT = "brain-core:cycle"
SOURCE = "validate-cycle:failure"

CORRECTIVE = corrective.Corrective(
    title="Fix brain-validate failures",
    source=SOURCE,
    role="linter",
    priority="P1",
    slug="validate-cycle-fix",
    acceptance=(
        "brain-validate exits 0; the structural/data integrity issue it reported "
        "is diagnosed and fixed."
    ),
)


def append_log(brain: Path, entry: str) -> None:
    journal.append_line(f"- {clock.utc_now()}: {entry}", brain)


def append_corrective_task(brain: Path) -> tuple[bool, str]:
    """Завести задачу на провал валидации, если такой ещё нет."""
    added = corrective.append(brain, [CORRECTIVE])
    if not added:
        return False, f"Corrective task with source '{SOURCE}' already exists. Skipping."
    return True, f"Appended corrective task {added[0]} (source '{SOURCE}')."


def run_cycle(brain: Path, *, dry_run: bool) -> dict[str, Any]:
    command = ["brain-validate"]
    result: dict[str, Any] = {"command": " ".join(command), "mode": "dry-run" if dry_run else "apply"}
    try:
        proc = subprocess.run(
            command, cwd=str(brain), capture_output=True, text=True, timeout=60, check=False
        )
        result["stdout"] = proc.stdout.strip()
        result["stderr"] = proc.stderr.strip()
        result["exit_code"] = proc.returncode

        if proc.returncode == 0:
            result["status"] = "success"
            result["message"] = "Brain validation successful."
            if not dry_run:
                append_log(brain, "validate-cycle: OK - Brain validation passed.")
        else:
            result["status"] = "failure"
            result["message"] = "Brain validation failed."
            if not dry_run:
                created, message = append_corrective_task(brain)
                result["task_created"] = created
                result["task_message"] = message
                append_log(brain, f"validate-cycle: FAILED - {message}")
    except FileNotFoundError:
        result["status"] = "error"
        result["message"] = "Error: 'brain-validate' command not found. Is the brain installed?"
        result["exit_code"] = -1
    except subprocess.TimeoutExpired:
        result["status"] = "error"
        result["message"] = "Error: 'brain-validate' command timed out."
        result["exit_code"] = -1
    except Exception as exc:  # pragma: no cover — сеть отказов шире, чем перечисленные
        result["status"] = "error"
        result["message"] = f"An unexpected error occurred: {exc}"
        result["exit_code"] = -1
    return result


def run(args: argparse.Namespace) -> int:
    brain = runner.resolve_brain(args)
    if not brain.is_dir():
        print(
            f"Error: Brain path not found at '{brain}'. Is BRAIN_PATH set correctly?",
            file=sys.stderr,
        )
        return 1

    result = run_cycle(brain, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Status: {result.get('status', 'unknown')}")
        print(f"Message: {result.get('message', 'N/A')}")
        if result.get("task_message"):
            print(f"Task: {result.get('task_message')}")
        if result.get("stderr"):
            print("\n--- Stderr ---")
            print(result["stderr"])
            print("----------------")
    # Код выхода информативен: провал валидации виден таймеру, а не только в отчёте.
    return 0 if result.get("status") == "success" else int(result.get("exit_code", 1) or 1)


def unit(args: argparse.Namespace) -> systemd.UnitSpec:
    brain = runner.resolve_brain(args)
    return systemd.UnitSpec(
        name=NAME,
        service_description="Run brain-validate cycle",
        timer_description="Run brain-validate cycle daily",
        command=systemd.resolve_command(NAME),
        exec_args=["--brain", str(brain), "--apply"],
        timer_options=[("OnCalendar", "daily"), ("RandomizedDelaySec", "6h"), ("Persistent", "true")],
        unit_options=[("Wants", f"{NAME}.timer")],
        working_dir=brain,
        environment=[("BRAIN_PATH", str(brain))],
    )


SPEC = runner.CycleSpec(
    name=NAME,
    description="Runs a validation cycle on the brain.",
    install_description="Install the brain-validate-cycle user systemd timer.",
    run=run,
    unit=unit,
    default_agent=DEFAULT_AGENT,
    mode_required=True,
)
