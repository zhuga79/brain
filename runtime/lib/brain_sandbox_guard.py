"""Runtime guardrails for launching real agents.

Dry-runs and render/tests are safe inside constrained Codex sandboxes. Live
agent launches are not: they need real filesystem, terminal, MCP, and user-bus
access. This module keeps that rule consistent across dashboard/orchestrator.
"""

from __future__ import annotations

from collections.abc import Mapping
import os


class SandboxLaunchError(RuntimeError):
    """Raised when code attempts a live agent launch from a sandbox."""


_SANDBOX_ENV_FLAGS = (
    "BRAIN_SANDBOX_AGENT_LAUNCH_GUARD",
    "CODEX_SANDBOX_NETWORK_DISABLED",
    "CODEX_SANDBOX",
    "SANDBOX_MODE",
)


def sandbox_reason(env: Mapping[str, str] | None = None) -> str:
    env = env or os.environ
    reasons: list[str] = []
    for key in _SANDBOX_ENV_FLAGS:
        value = str(env.get(key) or "").strip()
        if value and value not in {"0", "false", "False", "no", "NO"}:
            reasons.append(f"{key}={value}")
    return ", ".join(reasons)


def assert_not_sandbox_agent_launch(*, dry_run: bool, action: str) -> None:
    if dry_run:
        return
    reason = sandbox_reason()
    if not reason:
        return
    raise SandboxLaunchError(
        f"Refusing {action} inside sandbox ({reason}). "
        "Use --dry-run for inspection, then run the real launch outside sandbox."
    )
