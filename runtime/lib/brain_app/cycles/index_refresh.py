"""index-refresh: пересборка поискового индекса, но только когда он устарел.

Безусловная ежедневная пересборка на большом дереве занимает минуты и ничего не
меняет. Цикл сначала спрашивает `brain-index stale` и уходит, если индекс свеж.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from brain_core import clock, journal

from . import runner, systemd

NAME = "brain-index-refresh"
DEFAULT_AGENT = "brain-core:index-cycle"


def append_log(brain: Path, entry: str) -> None:
    journal.append_line(f"- {clock.utc_now()}: {entry}", brain)


def run_cycle(brain: Path, *, dry_run: bool) -> dict[str, Any]:
    stale_command = ["brain-index", "stale"]
    rebuild_command = ["brain-index", "rebuild"]
    result: dict[str, Any] = {
        "stale_command": " ".join(stale_command),
        "mode": "dry-run" if dry_run else "apply",
    }
    try:
        stale_proc = subprocess.run(
            stale_command, cwd=str(brain), capture_output=True, text=True, timeout=60, check=False
        )
        result["stale_check"] = {
            "stdout": stale_proc.stdout.strip(),
            "stderr": stale_proc.stderr.strip(),
            "exit_code": stale_proc.returncode,
        }

        if stale_proc.returncode == 0:
            result["status"] = "success"
            result["message"] = "Index is fresh."
            if not dry_run:
                append_log(brain, "index-refresh: fresh")
            return result

        result["message"] = "Index is stale."
        if dry_run:
            result["status"] = "success"
            result["action"] = "would_rebuild"
            return result

        result["rebuild_command"] = " ".join(rebuild_command)
        rebuild_proc = subprocess.run(
            rebuild_command, cwd=str(brain), capture_output=True, text=True, timeout=300, check=False
        )
        result["rebuild"] = {
            "stdout": rebuild_proc.stdout.strip(),
            "stderr": rebuild_proc.stderr.strip(),
            "exit_code": rebuild_proc.returncode,
        }
        if rebuild_proc.returncode == 0:
            result["status"] = "success"
            result["message"] = "Index was stale and has been rebuilt."
            append_log(brain, "index-refresh: rebuilt")
        else:
            result["status"] = "failure"
            result["message"] = "Index rebuild failed."
            append_log(brain, f"index-refresh: FAILED - Rebuild exited with {rebuild_proc.returncode}")
    except FileNotFoundError as exc:
        result["status"] = "error"
        result["message"] = f"Error: '{exc.filename}' command not found. Is the brain installed?"
        result["exit_code"] = -1
    except subprocess.TimeoutExpired:
        result["status"] = "error"
        result["message"] = "Error: Command timed out."
        result["exit_code"] = -1
    except Exception as exc:  # pragma: no cover — сеть отказов шире, чем перечисленные
        result["status"] = "error"
        result["message"] = f"An unexpected error occurred: {exc}"
        result["exit_code"] = -1
    return result


def run(args: argparse.Namespace) -> int:
    brain = runner.resolve_brain(args)
    if not brain.is_dir():
        print(f"Error: Brain path not found at '{brain}'. Is BRAIN_PATH set correctly?", file=sys.stderr)
        return 1

    result = run_cycle(brain, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Status: {result.get('status', 'unknown')}")
        print(f"Message: {result.get('message', 'N/A')}")
        if result.get("stderr"):
            print("\n--- Stderr ---")
            print(result["stderr"])
            print("----------------")
    return 0 if result.get("status") == "success" else 1


def unit(args: argparse.Namespace) -> systemd.UnitSpec:
    brain = runner.resolve_brain(args)
    return systemd.UnitSpec(
        name=NAME,
        service_description="Run brain-index-refresh cycle",
        timer_description="Run brain-index-refresh cycle daily",
        command=systemd.resolve_command(NAME),
        exec_args=["--brain", str(brain), "--apply"],
        timer_options=[("OnCalendar", "daily"), ("RandomizedDelaySec", "4h"), ("Persistent", "true")],
        unit_options=[("Wants", f"{NAME}.timer")],
        working_dir=brain,
        environment=runner.service_environment(brain),
    )


SPEC = runner.CycleSpec(
    name=NAME,
    description="Runs an index refresh cycle on the brain.",
    install_description="Install the brain-index-refresh user systemd timer.",
    run=run,
    unit=unit,
    default_agent=DEFAULT_AGENT,
    mode_required=True,
)
