"""Shared helpers for the dashboard launch-proposal queue.

Both brain-dashboard (status updates after a launch) and brain-queue-cycle
(daily proposal builder) read-modify-write the same proposals.json. These
helpers provide a process-level lock plus atomic writes so concurrent runs do
not lose updates or leave a half-written file.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterator

try:  # POSIX file locking; the runtime targets Linux.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]


# Canonical set of launch clients accepted by the dashboard and the
# queue-cycle proposal builder. Single source of truth for both.
ALLOWED_CLIENTS: tuple[str, ...] = (
    "claude",
    "codex",
    "gemini",
    "ollama",
    "opencode",
    "kilocode",
)


def proposals_path(brain: Path) -> Path:
    return brain / ".brain" / "launch-queue" / "proposals.json"


def _lock_path(brain: Path) -> Path:
    return brain / ".brain" / "launch-queue" / ".proposals.lock"


@contextlib.contextmanager
def lock(brain: Path) -> Iterator[None]:
    """Hold an exclusive lock around a read-modify-write of proposals.json.

    Keep the critical section short — never wrap a long subprocess in it."""
    lp = _lock_path(brain)
    lp.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:  # pragma: no cover - no advisory locks available
        yield
        return
    fd = os.open(str(lp), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON to a temp file in the same directory, fsync, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".proposals.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
