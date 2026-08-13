from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from unittest import mock

import pytest

import brain_webhook


SAMPLE_EVENT = {
    "task_id": "t-webhook",
    "agent_id": "agent-webhook",
    "summary": "done",
    "timestamp": "2026-05-13T12:00:00Z",
}


def _dead_letter_entries(brain: Path) -> list[dict]:
    path = brain / ".webhooks" / "dead-letter.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_webhooks_config(brain: Path, config: dict) -> None:
    (brain / "config").mkdir(parents=True, exist_ok=True)
    (brain / "config" / "webhooks.json").write_text(json.dumps(config))


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/hook",
        "gopher://example.com/hook",
        "https:///missing-host",
        "http://127.0.0.1/hook",
        "http://10.0.0.1/hook",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/hook",
    ],
)
def test_validate_webhook_url_rejects_unsafe_targets(monkeypatch, url):
    monkeypatch.delenv("BRAIN_WEBHOOK_ALLOW_LOOPBACK", raising=False)

    with pytest.raises(ValueError):
        brain_webhook.validate_webhook_url(url)


def test_validate_webhook_url_allows_loopback_when_explicit(monkeypatch):
    monkeypatch.setenv("BRAIN_WEBHOOK_ALLOW_LOOPBACK", "1")

    brain_webhook.validate_webhook_url("http://127.0.0.1:9000/hook")


def test_send_uses_proxy_free_opener(monkeypatch):
    opened = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class FakeOpener:
        def open(self, req, timeout):
            opened["request"] = req
            opened["timeout"] = timeout
            return FakeResponse()

    def fake_build_opener(handler):
        opened["handler"] = handler
        return FakeOpener()

    monkeypatch.setenv("BRAIN_WEBHOOK_ALLOW_LOOPBACK", "1")
    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)

    brain_webhook._send(
        "http://127.0.0.1:9000/hook",
        b'{"ok": true}',
        {"Content-Type": "application/json"},
        7,
    )

    assert opened["timeout"] == 7
    assert isinstance(opened["handler"], urllib.request.ProxyHandler)
    assert opened["request"].data == b'{"ok": true}'


def test_formatters_cover_telegram_slack_and_generic():
    telegram = brain_webhook.format_telegram(
        SAMPLE_EVENT,
        {"chat_id": "chat-1"},
    )
    assert telegram["chat_id"] == "chat-1"
    assert SAMPLE_EVENT["task_id"] in telegram["text"]
    assert SAMPLE_EVENT["agent_id"] in telegram["text"]
    assert SAMPLE_EVENT["summary"] in telegram["text"]

    telegram_without_summary = brain_webhook.format_telegram(
        {**SAMPLE_EVENT, "summary": ""},
        {"chat_id": "chat-1"},
    )
    assert "-" in telegram_without_summary["text"] or "—" in telegram_without_summary["text"]

    slack = brain_webhook.format_slack(SAMPLE_EVENT, {})
    assert slack["text"] == "task-done `t-webhook` by `agent-webhook`"
    assert len(slack["blocks"]) == 2

    slack_without_summary = brain_webhook.format_slack({**SAMPLE_EVENT, "summary": ""}, {})
    assert len(slack_without_summary["blocks"]) == 1

    generic = brain_webhook.format_generic(SAMPLE_EVENT, {})
    assert generic == SAMPLE_EVENT
    assert generic is not SAMPLE_EVENT


def test_load_webhooks_config_missing_file_returns_empty(tmp_path):
    assert brain_webhook._load_webhooks_config(str(tmp_path)) == {}


def test_fire_task_done_no_brain_path_warns(monkeypatch, capsys):
    monkeypatch.delenv("BRAIN_PATH", raising=False)

    brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path="")

    assert "BRAIN_PATH not set" in capsys.readouterr().err


def test_fire_task_done_corrupt_config_warns(tmp_path, capsys):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "webhooks.json").write_text("{not-json")

    brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path=str(tmp_path))

    assert "could not load webhooks config" in capsys.readouterr().err


def test_fire_task_done_empty_or_disabled_hooks_are_noops(tmp_path):
    _write_webhooks_config(
        tmp_path,
        {"task_done": [{"type": "generic", "url": "https://example.com/hook", "enabled": False}]},
    )

    with mock.patch.object(brain_webhook, "_send") as send:
        brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path=str(tmp_path))

    send.assert_not_called()


def test_fire_task_done_sends_generic_payload(tmp_path):
    captured = {}
    _write_webhooks_config(
        tmp_path,
        {"task_done": [{"type": "unknown", "url": "https://example.com/hook"}]},
    )

    def fake_send(url, payload, headers, timeout):
        captured["url"] = url
        captured["payload"] = json.loads(payload.decode())
        captured["headers"] = headers
        captured["timeout"] = timeout

    with mock.patch.object(brain_webhook, "_send", side_effect=fake_send):
        brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path=str(tmp_path), timeout=11)

    assert captured["url"] == "https://example.com/hook"
    assert captured["payload"] == SAMPLE_EVENT
    assert captured["headers"]["User-Agent"] == "brain-task/2.0"
    assert captured["timeout"] == 11


def test_fire_task_done_invalid_url_and_delivery_errors_are_masked(tmp_path, capsys):
    secret_url = "https://api.telegram.org/bot123456:SECRET/sendMessage"
    _write_webhooks_config(
        tmp_path,
        {
            "task_done": [
                {"type": "generic", "url": "http://127.0.0.1/hook"},
                {"type": "telegram", "url": secret_url, "chat_id": "chat-1"},
            ]
        },
    )

    with mock.patch.object(brain_webhook, "_send", side_effect=OSError("bot123456:SECRET failed")):
        brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path=str(tmp_path))

    stderr = capsys.readouterr().err
    assert "invalid URL" in stderr
    assert "delivery failed" in stderr
    assert "bot123456:SECRET" not in stderr
    assert "bot***" in stderr


def test_deliver_requires_url(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("BRAIN_WEBHOOK_URL", raising=False)

    assert brain_webhook.deliver("t1", "agent", str(tmp_path)) == 1

    assert "BRAIN_WEBHOOK_URL not set" in capsys.readouterr().err


def test_deliver_success_sends_payload_and_headers(monkeypatch, tmp_path):
    calls = []

    def fake_send(url, payload, headers, timeout):
        calls.append((url, json.loads(payload.decode()), headers, timeout))

    monkeypatch.setenv("BRAIN_WEBHOOK_URL", "https://example.com/hook")
    monkeypatch.setenv("BRAIN_WEBHOOK_TIMEOUT_SEC", "9")
    monkeypatch.setenv("BRAIN_WEBHOOK_RETRIES", "3")
    monkeypatch.setattr(brain_webhook, "_send", fake_send)

    assert brain_webhook.deliver("t-task", "agent-a", str(tmp_path)) == 0

    assert len(calls) == 1
    url, payload, headers, timeout = calls[0]
    assert url == "https://example.com/hook"
    assert payload["event"] == "task-done"
    assert payload["task_id"] == "t-task"
    assert payload["agent_id"] == "agent-a"
    assert payload["state"] == "done"
    assert payload["brain_path"] == str(tmp_path)
    assert headers["X-Brain-Attempt"] == "1"
    assert headers["X-Brain-Idempotency-Key"]
    assert timeout == 9
    assert not (tmp_path / ".webhooks" / "dead-letter.jsonl").exists()


def test_deliver_retries_then_dead_letters(monkeypatch, tmp_path, capsys):
    calls = []

    def failing_send(url, payload, headers, timeout):
        calls.append((url, json.loads(payload.decode()), headers, timeout))
        raise OSError("network down")

    monkeypatch.setenv("BRAIN_WEBHOOK_URL", "https://example.com/hook")
    monkeypatch.setenv("BRAIN_WEBHOOK_RETRIES", "2")
    monkeypatch.setattr(brain_webhook, "_send", failing_send)
    monkeypatch.setattr(brain_webhook.time, "sleep", lambda _seconds: None)

    assert brain_webhook.deliver("t-dead", "agent-b", str(tmp_path)) == 0

    assert len(calls) == 2
    assert [call[2]["X-Brain-Attempt"] for call in calls] == ["1", "2"]
    entries = _dead_letter_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["url"] == "https://example.com/hook"
    assert entries[0]["payload"]["task_id"] == "t-dead"
    assert entries[0]["error"] == "network down"
    assert "queued in .webhooks/dead-letter.jsonl" in capsys.readouterr().err


def test_deliver_succeeds_after_retry_without_dead_letter(monkeypatch, tmp_path):
    attempts = {"count": 0}

    def flaky_send(url, payload, headers, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise OSError("temporary")

    monkeypatch.setenv("BRAIN_WEBHOOK_URL", "https://example.com/hook")
    monkeypatch.setenv("BRAIN_WEBHOOK_RETRIES", "3")
    monkeypatch.setattr(brain_webhook, "_send", flaky_send)
    monkeypatch.setattr(brain_webhook.time, "sleep", lambda _seconds: None)

    assert brain_webhook.deliver("t-ok", "agent-c", str(tmp_path)) == 0

    assert attempts["count"] == 2
    assert not (tmp_path / ".webhooks" / "dead-letter.jsonl").exists()


def test_replay_requires_url(monkeypatch, tmp_path, capsys):
    dl = tmp_path / "dead-letter.jsonl"
    dl.write_text("")
    monkeypatch.delenv("BRAIN_WEBHOOK_URL", raising=False)

    assert brain_webhook.replay(str(dl)) == 1

    assert "BRAIN_WEBHOOK_URL not set" in capsys.readouterr().err


def test_replay_delivers_all_entries_and_clears_file(monkeypatch, tmp_path, capsys):
    dl = tmp_path / "dead-letter.jsonl"
    dl.write_text(
        json.dumps({"payload": {"task_id": "t1"}, "idempotency_key": "k1"}) + "\n"
        + json.dumps({"payload": {"task_id": "t2"}, "idempotency_key": "k2"}) + "\n"
    )
    calls = []

    def fake_send(url, payload, headers, timeout):
        calls.append((url, json.loads(payload.decode()), headers, timeout))

    monkeypatch.setenv("BRAIN_WEBHOOK_URL", "https://example.com/replay")
    monkeypatch.setenv("BRAIN_WEBHOOK_TIMEOUT_SEC", "4")
    monkeypatch.setattr(brain_webhook, "_send", fake_send)

    assert brain_webhook.replay(str(dl)) == 0

    assert dl.read_text() == ""
    assert [call[1]["task_id"] for call in calls] == ["t1", "t2"]
    assert [call[2]["X-Brain-Idempotency-Key"] for call in calls] == ["k1", "k2"]
    assert all(call[2]["X-Brain-Replay"] == "1" for call in calls)
    assert all(call[3] == 4 for call in calls)
    assert "replayed=2 remaining=0" in capsys.readouterr().out


def test_replay_keeps_failed_entries_with_retry_error(monkeypatch, tmp_path, capsys):
    dl = tmp_path / "dead-letter.jsonl"
    dl.write_text(
        json.dumps({"payload": {"task_id": "t1"}, "idempotency_key": "k1"}) + "\n"
        + json.dumps({"payload": {"task_id": "t2"}, "idempotency_key": "k2"}) + "\n"
    )

    def partly_failing_send(url, payload, headers, timeout):
        if json.loads(payload.decode())["task_id"] == "t2":
            raise OSError("still down")

    monkeypatch.setenv("BRAIN_WEBHOOK_URL", "https://example.com/replay")
    monkeypatch.setattr(brain_webhook, "_send", partly_failing_send)

    assert brain_webhook.replay(str(dl)) == 0

    remaining = [json.loads(line) for line in dl.read_text().splitlines()]
    assert len(remaining) == 1
    assert remaining[0]["payload"]["task_id"] == "t2"
    assert remaining[0]["last_retry_error"] == "still down"
    assert "replayed=1 remaining=1" in capsys.readouterr().out


def test_fire_event_cli_dispatches_task_done(monkeypatch):
    captured = {}

    def fake_fire(event):
        captured.update(event)

    monkeypatch.setattr(brain_webhook, "fire_task_done", fake_fire)

    rc = brain_webhook._fire_event_cli(
        ["task_done", "--task-id", "t-cli", "--agent", "agent-cli", "--summary", "done"]
    )

    assert rc == 0
    assert captured["task_id"] == "t-cli"
    assert captured["agent_id"] == "agent-cli"
    assert captured["summary"] == "done"
    assert captured["timestamp"].endswith("Z")


def test_fire_event_cli_rejects_unknown_event(capsys):
    assert brain_webhook._fire_event_cli(
        ["unknown", "--task-id", "t-cli", "--agent", "agent-cli"]
    ) == 2

    assert "Unknown event" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["deliver"],
        ["replay"],
        ["missing"],
    ],
)
def test_main_usage_errors(args, capsys):
    assert brain_webhook.main(args) == 2
    assert ("Usage:" in capsys.readouterr().err) or args == ["missing"]


def test_main_dispatches_deliver_replay_and_fire_event(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr(
        brain_webhook,
        "deliver",
        lambda task_id, agent_id, brain_path: calls.append(("deliver", task_id, agent_id, brain_path)) or 0,
    )
    monkeypatch.setattr(
        brain_webhook,
        "replay",
        lambda dl_path: calls.append(("replay", dl_path)) or 0,
    )
    monkeypatch.setattr(
        brain_webhook,
        "_fire_event_cli",
        lambda args: calls.append(("fire-event", tuple(args))) or 0,
    )

    assert brain_webhook.main(["deliver", "t1", "agent", str(tmp_path)]) == 0
    assert brain_webhook.main(["replay", str(tmp_path / "dl.jsonl")]) == 0
    assert brain_webhook.main(["fire-event", "task_done", "--task-id", "t1", "--agent", "a"]) == 0

    assert calls == [
        ("deliver", "t1", "agent", str(tmp_path)),
        ("replay", str(tmp_path / "dl.jsonl")),
        ("fire-event", ("task_done", "--task-id", "t1", "--agent", "a")),
    ]
