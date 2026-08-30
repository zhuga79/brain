"""Core data types and utilities shared across brain_federation modules."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
SEVERITIES = ("block", "review", "warn", "info")
TASK_ID_RE = __import__("re").compile(r"^[A-Za-z0-9_.:-]+$")
AGENT_ID_RE = __import__("re").compile(r"^[A-Za-z0-9_.:-]+$")

NODE_ID_ENV = "BRAIN_NODE_ID"
FEDERATION_CONFIG_FILE = "config/federation.json"
NODE_ID_DEFAULT = "anonymous"

RUNTIME_PATHS = (
    ".locks/",
    ".brain/",
    ".provider-health.json",
    "handoff/ORCHESTRATOR_HANDOFF.md",
    "wiki/_views/",
)
GENERATED_IGNORE_PATTERNS = RUNTIME_PATHS

SECRET_RE = __import__("re").compile(
    r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=:-]{8,}"
)


@dataclass
class Finding:
    code: str
    severity: str
    path: str
    message: str
    hint: str = ""

    def as_json(self) -> dict[str, str]:
        item = {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
        }
        if self.hint:
            item["hint"] = self.hint
        return item


def brain_path(value: str | None) -> Path:
    return Path(value or os.environ.get("BRAIN_PATH", str(Path.home() / "brain"))).expanduser()


def _config_node_id(brain: Path) -> str:
    """Read node identity from <brain>/config/federation.json, if present."""
    cfg = brain / FEDERATION_CONFIG_FILE
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    value = data.get("node_id")
    if isinstance(value, str):
        return value.strip()
    return ""


def _git_email(brain: Path) -> str:
    """Read `git config --get user.email` inside the vault (repo root == vault)."""
    try:
        res = subprocess.run(
            ["git", "-C", str(brain), "config", "--get", "user.email"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError:
        return ""
    if res.returncode != 0:
        return ""
    return res.stdout.strip()


def node_id(brain: Path | None = None) -> str:
    """Resolve the stable federation node identity for this vault.

    Precedence:
      1. ``$BRAIN_NODE_ID`` env var — explicit operator override;
      2. ``<brain>/config/federation.json`` → ``node_id`` field;
      3. ``git config --get user.email`` in the vault (git repo root);
      4. ``"anonymous"`` — deterministic fallback so a single-user vault with
         no federation config always keeps working and never raises.

    The value feeds ``node=...`` audit rows in ``wiki/log.md`` written by
    import-tasks and sync, so every operation is attributable to the node
    that produced it (t-2026-08-16-multi-user-federation-readines-s1).
    """
    env = os.environ.get(NODE_ID_ENV, "").strip()
    if env:
        return env
    vault = brain_path(brain)
    configured = _config_node_id(vault)
    if configured:
        return configured
    email = _git_email(vault)
    if email:
        return email
    return NODE_ID_DEFAULT


def result(mode: str, repo: Path | None, brain: Path | None, findings: list[Finding]) -> dict[str, Any]:
    summary = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        summary[finding.severity] = summary.get(finding.severity, 0) + 1
    return {
        "ok": summary.get("block", 0) == 0,
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "repo": str(repo.resolve()) if repo else "",
        "brain": str(brain.resolve()) if brain else "",
        "summary": summary,
        "findings": [finding.as_json() for finding in findings],
    }


def exit_code(findings: list[Finding]) -> int:
    return 1 if any(f.severity == "block" for f in findings) else 0


def has_block(findings: list[Finding]) -> bool:
    return any(f.severity == "block" for f in findings)


def emit(data: dict[str, Any], json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(f"brain-federation {data['mode']}: {'OK' if data['ok'] else 'BLOCKED'}")
    summary = data.get("summary", {})
    print(
        "  findings: "
        f"block={summary.get('block', 0)} "
        f"review={summary.get('review', 0)} "
        f"warn={summary.get('warn', 0)} "
        f"info={summary.get('info', 0)}"
    )
    for finding in data.get("findings", []):
        path = f" {finding['path']}" if finding.get("path") else ""
        print(f"  [{finding['severity']}] {finding['code']}{path}: {finding['message']}")
        if finding.get("hint"):
            print(f"      hint: {finding['hint']}")


def parse_task_file(
    path: Path,
    source: str,
    flag_in_progress: bool = True,
) -> tuple[list[dict[str, Any]], list[Finding]]:
    """Parse a task file and return tasks and findings."""
    import brain_task_parser  # noqa: PLC0415

    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    text = path.read_text(encoding="utf-8", errors="replace")
    tasks: list[dict[str, Any]] = []
    findings: list[Finding] = []
    for block in brain_task_parser.find_blocks(text):
        parsed = brain_task_parser.parse_block(block)
        if not parsed:
            continue
        first_line = block.split("\n")[0]
        idx = text.find(first_line)
        line_no = text[:idx].count("\n") + 1 if idx >= 0 else 0
        tasks.append({
            "id": parsed["id"],
            "title": parsed["title"],
            "state": parsed["state"],
            "priority": parsed["prio"],
            "role": parsed.get("role", ""),
            "mode": parsed.get("mode", ""),
            "acceptance": parsed.get("acceptance", ""),
            "path": str(path),
            "source": source,
            "line": line_no,
        })

    if flag_in_progress:
        for task in tasks:
            if task["state"] == "~":
                findings.append(
                    Finding(
                        "task-imported-in-progress",
                        "block",
                        f"{path}:{task['line']}",
                        f"task {task['id']} is imported as in-progress",
                        "import proposed tasks as open; local agents must acquire locks themselves",
                    )
                )
    return tasks, findings
