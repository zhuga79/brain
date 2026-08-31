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
# Git email is operator PII and is only published to the synced audit log
# when the operator explicitly opts in (env or federation.json), never by
# default. See node_id().
NODE_GIT_EMAIL_ENV = "BRAIN_NODE_ID_FROM_GIT"
NODE_GIT_EMAIL_CONFIG = "node_id_from_git"
# Charset for node identity as it appears in wiki/log.md audit rows. This is
# the same defensive intent as AGENT_ID_RE/TASK_ID_RE: the value is embedded
# verbatim in a `## [ts] op | id | agent | extra` line, so newlines and the
# positional `|` separator must never reach the journal. `@` is allowed so
# email-derived identities remain usable.
NODE_ID_RE = __import__("re").compile(r"^[A-Za-z0-9_.:@+-]+$")

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


def _federation_config(brain: Path) -> dict[str, Any]:
    """Return <brain>/config/federation.json as a dict ({} on any problem)."""
    cfg = brain / FEDERATION_CONFIG_FILE
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _config_node_id(brain: Path) -> str:
    """Read node identity from <brain>/config/federation.json, if present."""
    value = _federation_config(brain).get("node_id")
    if isinstance(value, str):
        return value.strip()
    return ""


def _git_email_enabled(brain: Path) -> bool:
    """Whether git user.email may be published as node identity — explicit opt-in only.

    Default is *off*: git user.email is operator PII and must not leak into a
    journal that is synced and pushed to every federation peer unless the
    operator explicitly allows it. Enabled via $BRAIN_NODE_ID_FROM_GIT=1 or
    `"node_id_from_git": true` in config/federation.json.
    """
    flag = os.environ.get(NODE_GIT_EMAIL_ENV, "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    configured = _federation_config(brain).get(NODE_GIT_EMAIL_CONFIG)
    return configured is True


_git_email_cache: dict[str, str] = {}


def _git_email(brain: Path) -> str:
    """Read (and cache per-vault) `git config --get user.email`."""
    try:
        key = str(brain.resolve())
    except OSError:
        return ""
    if key in _git_email_cache:
        return _git_email_cache[key]
    try:
        res = subprocess.run(
            ["git", "-C", str(brain), "config", "--get", "user.email"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        _git_email_cache[key] = ""
        return ""
    if res.returncode != 0:
        _git_email_cache[key] = ""
        return ""
    _git_email_cache[key] = res.stdout.strip()
    return _git_email_cache[key]


def _validated_or_raise(value: str, source: str) -> str:
    """Validate a node identity before it is embedded in a journal row.

    A configured identity that does not fit the charset (newline, `|`, or any
    char outside ``NODE_ID_RE``) is an explicit-config error: raising (rather
    than silently falling back) surfaces the misconfiguration so the audit log
    can never be forged by an injected value.
    """
    if not NODE_ID_RE.match(value):
        raise ValueError(
            f"invalid federation node identity in {source}: value must match "
            f"{NODE_ID_RE.pattern!r} and must not contain a newline or '|'; "
            f"got {value!r}"
        )
    return value


def node_id(brain: Path | None = None) -> str:
    """Resolve the stable federation node identity for this vault.

    Precedence:
      1. ``$BRAIN_NODE_ID`` env var — explicit operator override;
      2. ``<brain>/config/federation.json`` → ``node_id`` field;
      3. git user.email — ONLY when the operator explicitly opts in
         (``$BRAIN_NODE_ID_FROM_GIT=1`` or ``"node_id_from_git": true`` in
         federation.json). Never used by default: it is operator PII that would
         otherwise leak into a journal synced to every federation peer.
      4. ``"anonymous"`` — deterministic default so a single-user vault with no
         federation config keeps working and never leaks identity.

    The value feeds ``node=...`` audit rows in ``wiki/log.md``. It is
    **self-declared and advisory** — a node names itself; nothing here verifies
    that claim, so the rows are an audit aid, not authentication. A configured
    identity (env or config) that would break the journal format raises
    ``ValueError`` rather than silently falling back (t-2026-08-16-...).
    """
    env = os.environ.get(NODE_ID_ENV, "").strip()
    if env:
        return _validated_or_raise(env, f"${NODE_ID_ENV}")
    vault = brain_path(brain)
    configured = _config_node_id(vault)
    if configured:
        return _validated_or_raise(configured, FEDERATION_CONFIG_FILE)
    if _git_email_enabled(vault):
        email = _git_email(vault)
        if email:
            return _validated_or_raise(email, "git config user.email")
    return NODE_ID_DEFAULT


def node_audit_extra(node: str, *parts: str) -> str:
    """Build the journal extra slot with ``node=`` always first.

    Federation audit rows use the canonical four-slot line
    (``op | id | agent | extra``). Node identity is self-declared and
    advisory, and it always lives in extra — never in the agent slot — so
    parsers see a stable ``node=`` token.
    """
    bits = [f"node={node}"]
    bits.extend(part for part in parts if part)
    return " | ".join(bits)


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
