"""brain_webhook — webhook delivery and dead-letter replay for Brain task events.

This module provides two entry-points:

1. Delivery (used by brain-task complete):
   python3 -m brain_webhook deliver <task_id> <agent_id> <brain_path>

2. Replay (used by brain-task webhook-replay):
   python3 -m brain_webhook replay <dead_letter_file> <webhook_url>

3. Multi-hook fire (Phase 15):
   python3 -m brain_webhook fire-event task_done --task-id ... --agent ...

Both modes read BRAIN_WEBHOOK_URL, BRAIN_WEBHOOK_TIMEOUT_SEC,
BRAIN_WEBHOOK_RETRIES from the environment.

Phase 15 additions:
- format_telegram / format_slack / format_generic formatters
- fire_task_done: reads $BRAIN_PATH/config/webhooks.json and fires all enabled hooks
- mask_token: redacts bot<TOKEN> patterns before writing to stderr
"""

from __future__ import annotations

import datetime
import ipaddress
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def validate_webhook_url(url: str) -> None:
    """Validate a webhook URL before making a request.

    Raises ValueError if the URL is unsafe:
    - Non-http(s) schemes (blocks file://, gopher://, ftp://, etc.)
    - Missing or empty hostname
    - Loopback / link-local / private IP addresses, unless
      BRAIN_WEBHOOK_ALLOW_LOOPBACK=1 is set in the environment.

    Hostname-based targets (not raw IPs) bypass the IP check because
    DNS resolution happens later and we deliberately avoid resolving
    at validation time (to stay fast and avoid TOCTOU). This means a
    DNS name that resolves to a private IP is not blocked here — that
    is an accepted trade-off for the typical dev/CI use-case.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"unsupported webhook URL scheme {parsed.scheme!r}; only http/https allowed"
        )
    hostname = parsed.hostname  # lowercased, brackets stripped for IPv6
    if not hostname:
        raise ValueError("webhook URL is missing a hostname")

    # Check if the hostname is a raw IP address and reject private ranges
    # unless the operator has explicitly opted-in via the env flag.
    allow_loopback = os.environ.get("BRAIN_WEBHOOK_ALLOW_LOOPBACK") == "1"
    if not allow_loopback:
        try:
            addr = ipaddress.ip_address(hostname)
        except ValueError:
            # Not an IP address (it's a DNS name) — skip IP-based checks.
            pass
        else:
            if addr.is_loopback or addr.is_link_local or addr.is_private or addr.is_reserved:
                raise ValueError(
                    f"webhook URL targets a restricted address {hostname!r}; "
                    "set BRAIN_WEBHOOK_ALLOW_LOOPBACK=1 to allow local/private targets"
                )


# ---------------------------------------------------------------------------
# Token masking
# ---------------------------------------------------------------------------

# Matches Telegram bot tokens embedded in URLs (bot<TOKEN> pattern).
# Telegram tokens look like: 123456789:ABCdef-ghIJKLmnopQRSTuvwxyz
_TOKEN_RE = re.compile(r"bot[A-Za-z0-9:_-]+")


def mask_token(text: str) -> str:
    """Replace bot<TOKEN> occurrences with 'bot***' to prevent secret leakage in logs."""
    return _TOKEN_RE.sub("bot***", text)


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def format_telegram(event: dict, config: dict) -> dict:
    """Return request body for Telegram sendMessage API.

    Args:
        event: task-done event dict with keys: task_id, agent_id, summary, timestamp.
        config: webhook config entry, must include 'chat_id'.

    Returns:
        dict suitable for JSON-encoding and POSTing to the Telegram sendMessage URL.
    """
    text = (
        f"✅ task-done\n"
        f"id: {event.get('task_id', '?')}\n"
        f"by: {event.get('agent_id', '?')}\n"
        f"summary: {event.get('summary', '') or '—'}"
    )
    return {"chat_id": config["chat_id"], "text": text}


def format_slack(event: dict, config: dict) -> dict:  # noqa: ARG001
    """Return request body for Slack incoming webhook.

    Args:
        event: task-done event dict with keys: task_id, agent_id, summary, timestamp.
        config: webhook config entry (unused for Slack; token is in the URL).

    Returns:
        dict suitable for JSON-encoding and POSTing to the Slack incoming webhook URL.
    """
    task_id = event.get("task_id", "?")
    agent_id = event.get("agent_id", "?")
    summary = event.get("summary", "")

    fallback = f"task-done `{task_id}` by `{agent_id}`"
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*task-done* `{task_id}` by `{agent_id}`",
            },
        }
    ]
    if summary:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"_{summary}_"},
            }
        )

    return {"text": fallback, "blocks": blocks}


def format_generic(event: dict, config: dict) -> dict:  # noqa: ARG001
    """Return raw event passthrough for generic webhook.

    Args:
        event: task-done event dict.
        config: webhook config entry (unused).

    Returns:
        The event dict unchanged (shallow copy).
    """
    return dict(event)


_FORMATTERS = {
    "telegram": format_telegram,
    "slack": format_slack,
    "generic": format_generic,
}

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_webhooks_config(brain_path: str) -> dict:
    """Load $BRAIN_PATH/config/webhooks.json.

    Returns an empty dict if the file doesn't exist (webhooks disabled).
    Raises json.JSONDecodeError or OSError on corrupt/unreadable file.
    """
    cfg_path = pathlib.Path(brain_path) / "config" / "webhooks.json"
    if not cfg_path.exists():
        return {}
    with cfg_path.open() as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Internal HTTP send helper
# ---------------------------------------------------------------------------

def _send(url: str, payload: bytes, headers: dict[str, str], timeout: int) -> None:
    """Send a single HTTP request. Raises on failure."""
    validate_webhook_url(url)  # raises ValueError on unsafe URL
    req = urllib.request.Request(url, data=payload, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout):
        pass


# ---------------------------------------------------------------------------
# fire_task_done — Phase 15 multi-hook dispatch
# ---------------------------------------------------------------------------

def fire_task_done(
    event: dict,
    brain_path: str | None = None,
    timeout: int = 5,
) -> None:
    """Fire all enabled task-done webhooks defined in $BRAIN_PATH/config/webhooks.json.

    For each enabled hook:
    1. Select formatter (telegram / slack / generic).
    2. Validate URL (SSRF guard).
    3. POST the formatted payload.

    Errors from individual hooks are written to stderr with tokens masked.
    A single failing hook does not block the others.

    Args:
        event: dict with at minimum: task_id, agent_id, summary, timestamp.
        brain_path: override for BRAIN_PATH env var (useful in tests).
        timeout: HTTP request timeout in seconds.
    """
    bp = brain_path or os.environ.get("BRAIN_PATH", "")
    if not bp:
        sys.stderr.write("warning: BRAIN_PATH not set, skipping webhooks\n")
        return

    try:
        cfg = _load_webhooks_config(bp)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"warning: could not load webhooks config: {exc}\n")
        return

    hooks = cfg.get("task_done", [])
    if not hooks:
        return  # webhooks not configured — silent no-op

    for hook in hooks:
        if not hook.get("enabled", True):
            continue  # skip disabled hooks

        hook_type = hook.get("type", "generic")
        url = hook.get("url", "")

        # Validate URL first — log masked URL on failure
        try:
            validate_webhook_url(url)
        except ValueError as exc:
            safe_url = mask_token(url)
            sys.stderr.write(
                f"warning: webhook ({hook_type}) skipped — invalid URL {safe_url!r}: {exc}\n"
            )
            continue

        # Select formatter
        formatter = _FORMATTERS.get(hook_type, format_generic)

        try:
            body = formatter(event, hook)
            payload = json.dumps(body).encode()
            _send(url, payload, {
                "Content-Type": "application/json",
                "User-Agent": "brain-task/2.0",
            }, timeout)
        except Exception as exc:  # noqa: BLE001
            safe_url = mask_token(url)
            sys.stderr.write(
                f"warning: webhook ({hook_type}) delivery failed to {safe_url!r}: {mask_token(str(exc))}\n"
            )


# ---------------------------------------------------------------------------
# Legacy deliver / replay entry-points
# ---------------------------------------------------------------------------

def deliver(task_id: str, agent_id: str, brain_path: str) -> int:
    """Send a task-done webhook event with retry and dead-letter fallback.

    Reads configuration from environment:
        BRAIN_WEBHOOK_URL      (required)
        BRAIN_WEBHOOK_TIMEOUT_SEC (default 5)
        BRAIN_WEBHOOK_RETRIES     (default 3)

    Returns 0 on success (or queued), 1 on config error.
    """
    url = os.environ.get("BRAIN_WEBHOOK_URL", "")
    if not url:
        print("BRAIN_WEBHOOK_URL not set", file=sys.stderr)
        return 1

    timeout = int(os.environ.get("BRAIN_WEBHOOK_TIMEOUT_SEC", "5"))
    max_tries = int(os.environ.get("BRAIN_WEBHOOK_RETRIES", "3"))
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    idem_key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{task_id}:{ts}"))

    payload = json.dumps({
        "event": "task-done",
        "task_id": task_id,
        "agent_id": agent_id,
        "state": "done",
        "timestamp": ts,
        "brain_path": brain_path,
    }).encode()

    last_err: str | None = None
    for attempt in range(1, max_tries + 1):
        try:
            _send(url, payload, {
                "Content-Type": "application/json",
                "User-Agent": "brain-task/2.0",
                "X-Brain-Idempotency-Key": idem_key,
                "X-Brain-Attempt": str(attempt),
            }, timeout)
            last_err = None
            break
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            if attempt < max_tries:
                time.sleep(2 ** (attempt - 1))

    if last_err:
        dl_dir = pathlib.Path(brain_path) / ".webhooks"
        dl_dir.mkdir(parents=True, exist_ok=True)
        entry = json.dumps({
            "url": url,
            "payload": json.loads(payload.decode()),
            "idempotency_key": idem_key,
            "failed_at": ts,
            "error": last_err,
        })
        (dl_dir / "dead-letter.jsonl").open("a").write(entry + "\n")
        print(
            f"WARN: webhook delivery failed after {max_tries} attempts ({last_err}); "
            f"queued in .webhooks/dead-letter.jsonl",
            file=sys.stderr,
        )

    return 0


def replay(dl_file_path: str) -> int:
    """Replay all entries from the dead-letter queue.

    Reads BRAIN_WEBHOOK_URL and BRAIN_WEBHOOK_TIMEOUT_SEC from environment.
    Returns 0.
    """
    url = os.environ.get("BRAIN_WEBHOOK_URL", "")
    if not url:
        print("BRAIN_WEBHOOK_URL not set", file=sys.stderr)
        return 1

    timeout = int(os.environ.get("BRAIN_WEBHOOK_TIMEOUT_SEC", "5"))
    dl_file = pathlib.Path(dl_file_path)
    entries = [json.loads(line) for line in dl_file.read_text().splitlines() if line.strip()]
    failed: list[dict] = []
    replayed = 0

    for entry in entries:
        payload = json.dumps(entry["payload"]).encode()
        idem_key = entry.get("idempotency_key", str(uuid.uuid4()))
        try:
            _send(url, payload, {
                "Content-Type": "application/json",
                "User-Agent": "brain-task/2.0",
                "X-Brain-Idempotency-Key": idem_key,
                "X-Brain-Replay": "1",
            }, timeout)
            replayed += 1
        except Exception as exc:  # noqa: BLE001
            entry["last_retry_error"] = str(exc)
            failed.append(entry)

    dl_file.write_text("\n".join(json.dumps(e) for e in failed) + ("\n" if failed else ""))
    print(f"replayed={replayed} remaining={len(failed)}")
    return 0


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _fire_event_cli(args: list[str]) -> int:
    """Handle: fire-event task_done --task-id <id> --agent <id> [--summary <s>]"""
    import argparse
    parser = argparse.ArgumentParser(prog="brain_webhook fire-event")
    parser.add_argument("event_name")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--summary", default="")
    ns = parser.parse_args(args)

    if ns.event_name != "task_done":
        print(f"Unknown event: {ns.event_name}", file=sys.stderr)
        return 2

    ts_now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fire_task_done({
        "task_id": ns.task_id,
        "agent_id": ns.agent,
        "summary": ns.summary,
        "timestamp": ts_now,
    })
    return 0


def main(args: list[str]) -> int:
    """Entry point for CLI invocation."""
    if not args:
        print("Usage: brain_webhook deliver <task_id> <agent_id> <brain_path>", file=sys.stderr)
        print("       brain_webhook replay <dead_letter_file>", file=sys.stderr)
        print("       brain_webhook fire-event task_done --task-id ... --agent ...", file=sys.stderr)
        return 2

    subcmd = args[0]
    if subcmd == "deliver":
        if len(args) < 4:
            print("Usage: brain_webhook deliver <task_id> <agent_id> <brain_path>", file=sys.stderr)
            return 2
        return deliver(args[1], args[2], args[3])
    elif subcmd == "replay":
        if len(args) < 2:
            print("Usage: brain_webhook replay <dead_letter_file>", file=sys.stderr)
            return 2
        return replay(args[1])
    elif subcmd == "fire-event":
        return _fire_event_cli(args[1:])
    else:
        print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
