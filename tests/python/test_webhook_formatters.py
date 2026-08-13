"""Tests for brain_webhook Phase 15 formatters and fire_task_done.

Covers:
- format_telegram: correct body structure
- format_slack: correct body structure
- format_generic: passthrough
- mask_token: redacts bot<TOKEN>
- fire_task_done with mocked _send: fires all enabled hooks
- fire_task_done: skips disabled hooks
- fire_task_done: rejects invalid SSRF URL, logs masked warning
- secrets test: no sensitive token in captured stderr
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import tempfile
import unittest.mock as mock

import pytest

# conftest.py already adds runtime/lib and runtime/mcp to sys.path
import brain_webhook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_EVENT = {
    "task_id": "t-2026-05-09-test",
    "agent_id": "claude-sonnet-test-abcd",
    "summary": "all done",
    "timestamp": "2026-05-09T12:00:00Z",
}

SAMPLE_TG_CONFIG = {
    "type": "telegram",
    "url": "https://api.telegram.org/bot12345:ABCdef/sendMessage",
    "chat_id": "-1001234567890",
    "enabled": True,
}

SAMPLE_SLACK_CONFIG = {
    "type": "slack",
    "url": "https://hooks.slack.com/services/T000/B000/xxxx",
    "enabled": True,
}

SAMPLE_GENERIC_CONFIG = {
    "type": "generic",
    "url": "https://example.com/webhook",
    "enabled": True,
}


# ---------------------------------------------------------------------------
# Formatter tests
# ---------------------------------------------------------------------------

class TestFormatTelegram:
    def test_returns_chat_id_and_text(self):
        body = brain_webhook.format_telegram(SAMPLE_EVENT, SAMPLE_TG_CONFIG)
        assert body["chat_id"] == SAMPLE_TG_CONFIG["chat_id"]
        assert "text" in body

    def test_text_contains_task_id(self):
        body = brain_webhook.format_telegram(SAMPLE_EVENT, SAMPLE_TG_CONFIG)
        assert SAMPLE_EVENT["task_id"] in body["text"]

    def test_text_contains_agent_id(self):
        body = brain_webhook.format_telegram(SAMPLE_EVENT, SAMPLE_TG_CONFIG)
        assert SAMPLE_EVENT["agent_id"] in body["text"]

    def test_text_contains_summary(self):
        body = brain_webhook.format_telegram(SAMPLE_EVENT, SAMPLE_TG_CONFIG)
        assert SAMPLE_EVENT["summary"] in body["text"]

    def test_text_contains_task_done_marker(self):
        body = brain_webhook.format_telegram(SAMPLE_EVENT, SAMPLE_TG_CONFIG)
        assert "task-done" in body["text"]

    def test_only_two_keys(self):
        body = brain_webhook.format_telegram(SAMPLE_EVENT, SAMPLE_TG_CONFIG)
        assert set(body.keys()) == {"chat_id", "text"}

    def test_missing_summary_defaults_to_dash(self):
        event = {**SAMPLE_EVENT, "summary": ""}
        body = brain_webhook.format_telegram(event, SAMPLE_TG_CONFIG)
        assert "—" in body["text"]


class TestFormatSlack:
    def test_returns_text_and_blocks(self):
        body = brain_webhook.format_slack(SAMPLE_EVENT, SAMPLE_SLACK_CONFIG)
        assert "text" in body
        assert "blocks" in body

    def test_text_contains_task_id(self):
        body = brain_webhook.format_slack(SAMPLE_EVENT, SAMPLE_SLACK_CONFIG)
        assert SAMPLE_EVENT["task_id"] in body["text"]

    def test_text_contains_agent_id(self):
        body = brain_webhook.format_slack(SAMPLE_EVENT, SAMPLE_SLACK_CONFIG)
        assert SAMPLE_EVENT["agent_id"] in body["text"]

    def test_blocks_is_nonempty_list(self):
        body = brain_webhook.format_slack(SAMPLE_EVENT, SAMPLE_SLACK_CONFIG)
        assert isinstance(body["blocks"], list)
        assert len(body["blocks"]) >= 1

    def test_summary_adds_extra_block(self):
        body = brain_webhook.format_slack(SAMPLE_EVENT, SAMPLE_SLACK_CONFIG)
        # summary is non-empty → 2 blocks
        assert len(body["blocks"]) == 2

    def test_no_summary_gives_one_block(self):
        event = {**SAMPLE_EVENT, "summary": ""}
        body = brain_webhook.format_slack(event, SAMPLE_SLACK_CONFIG)
        assert len(body["blocks"]) == 1

    def test_block_type_section(self):
        body = brain_webhook.format_slack(SAMPLE_EVENT, SAMPLE_SLACK_CONFIG)
        for block in body["blocks"]:
            assert block["type"] == "section"


class TestFormatGeneric:
    def test_passthrough(self):
        body = brain_webhook.format_generic(SAMPLE_EVENT, SAMPLE_GENERIC_CONFIG)
        assert body == SAMPLE_EVENT

    def test_returns_copy_not_same_object(self):
        body = brain_webhook.format_generic(SAMPLE_EVENT, SAMPLE_GENERIC_CONFIG)
        assert body is not SAMPLE_EVENT

    def test_config_unused(self):
        body = brain_webhook.format_generic(SAMPLE_EVENT, {})
        assert body == SAMPLE_EVENT


# ---------------------------------------------------------------------------
# mask_token tests
# ---------------------------------------------------------------------------

class TestMaskToken:
    def test_masks_bot_token_in_url(self):
        url = "https://api.telegram.org/bot12345:ABCdef-ghIJKL/sendMessage"
        result = brain_webhook.mask_token(url)
        assert "12345:ABCdef" not in result
        assert "bot***" in result

    def test_masks_bot_token_bare(self):
        result = brain_webhook.mask_token("bot99999:XYZabc")
        assert result == "bot***"

    def test_no_token_unchanged(self):
        text = "https://hooks.slack.com/services/T000/B000/xxxx"
        assert brain_webhook.mask_token(text) == text

    def test_masks_multiple_tokens(self):
        text = "bot111:aaa and bot222:bbb"
        result = brain_webhook.mask_token(text)
        assert "111" not in result
        assert "222" not in result
        assert result.count("bot***") == 2

    def test_empty_string(self):
        assert brain_webhook.mask_token("") == ""


# ---------------------------------------------------------------------------
# fire_task_done integration tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def webhooks_dir(tmp_path):
    """Create a temporary brain_path with a config/webhooks.json."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return tmp_path


def _write_webhooks_cfg(brain_path: pathlib.Path, cfg: dict) -> None:
    (brain_path / "config" / "webhooks.json").write_text(json.dumps(cfg))


class TestFireTaskDone:
    def test_fires_all_enabled_hooks(self, webhooks_dir):
        cfg = {
            "task_done": [
                {**SAMPLE_TG_CONFIG, "url": "https://api.telegram.org/bot12345:T/sendMessage"},
                {**SAMPLE_SLACK_CONFIG, "url": "https://hooks.slack.com/services/T/B/x"},
                {**SAMPLE_GENERIC_CONFIG, "url": "https://example.com/webhook"},
            ]
        }
        _write_webhooks_cfg(webhooks_dir, cfg)

        with mock.patch.object(brain_webhook, "_send") as mock_send:
            brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path=str(webhooks_dir))

        assert mock_send.call_count == 3

    def test_skips_disabled_hook(self, webhooks_dir):
        cfg = {
            "task_done": [
                {**SAMPLE_SLACK_CONFIG, "url": "https://hooks.slack.com/services/T/B/x"},
                {**SAMPLE_GENERIC_CONFIG, "url": "https://example.com/webhook", "enabled": False},
            ]
        }
        _write_webhooks_cfg(webhooks_dir, cfg)

        with mock.patch.object(brain_webhook, "_send") as mock_send:
            brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path=str(webhooks_dir))

        assert mock_send.call_count == 1

    def test_rejects_ssrf_private_ip_url(self, webhooks_dir, capsys):
        cfg = {
            "task_done": [
                {
                    "type": "generic",
                    "url": "http://192.168.1.1/evil",
                    "enabled": True,
                }
            ]
        }
        _write_webhooks_cfg(webhooks_dir, cfg)

        with mock.patch.object(brain_webhook, "_send") as mock_send:
            brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path=str(webhooks_dir))

        mock_send.assert_not_called()
        captured = capsys.readouterr()
        assert "warning" in captured.err.lower()

    def test_rejects_loopback_url(self, webhooks_dir):
        cfg = {
            "task_done": [
                {
                    "type": "generic",
                    "url": "http://127.0.0.1/hook",
                    "enabled": True,
                }
            ]
        }
        _write_webhooks_cfg(webhooks_dir, cfg)

        with mock.patch.object(brain_webhook, "_send") as mock_send:
            brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path=str(webhooks_dir))

        mock_send.assert_not_called()

    def test_one_failing_hook_does_not_block_others(self, webhooks_dir, capsys):
        cfg = {
            "task_done": [
                {**SAMPLE_SLACK_CONFIG, "url": "https://hooks.slack.com/services/T/B/first"},
                {**SAMPLE_SLACK_CONFIG, "url": "https://hooks.slack.com/services/T/B/second"},
            ]
        }
        _write_webhooks_cfg(webhooks_dir, cfg)

        call_count = [0]

        def failing_first(url, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("connection refused")

        with mock.patch.object(brain_webhook, "_send", side_effect=failing_first):
            brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path=str(webhooks_dir))

        assert call_count[0] == 2

    def test_no_config_file_is_silent_noop(self, tmp_path):
        """Missing config → no webhooks, no error."""
        brain_path = tmp_path / "empty_brain"
        brain_path.mkdir()
        (brain_path / "config").mkdir()

        with mock.patch.object(brain_webhook, "_send") as mock_send:
            brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path=str(brain_path))

        mock_send.assert_not_called()

    def test_no_brain_path_logs_warning(self, capsys, monkeypatch):
        monkeypatch.delenv("BRAIN_PATH", raising=False)
        brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path="")
        captured = capsys.readouterr()
        assert "warning" in captured.err.lower()

    def test_correct_payload_sent_to_telegram(self, webhooks_dir):
        cfg = {
            "task_done": [
                {**SAMPLE_TG_CONFIG, "url": "https://api.telegram.org/bot12345:T/sendMessage"},
            ]
        }
        _write_webhooks_cfg(webhooks_dir, cfg)

        captured_payload = {}

        def capture_send(url, payload, headers, timeout):
            captured_payload["data"] = json.loads(payload.decode())

        with mock.patch.object(brain_webhook, "_send", side_effect=capture_send):
            brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path=str(webhooks_dir))

        assert "chat_id" in captured_payload["data"]
        assert "text" in captured_payload["data"]
        assert SAMPLE_EVENT["task_id"] in captured_payload["data"]["text"]

    def test_correct_payload_sent_to_slack(self, webhooks_dir):
        cfg = {
            "task_done": [
                {**SAMPLE_SLACK_CONFIG, "url": "https://hooks.slack.com/services/T/B/x"},
            ]
        }
        _write_webhooks_cfg(webhooks_dir, cfg)

        captured_payload = {}

        def capture_send(url, payload, headers, timeout):
            captured_payload["data"] = json.loads(payload.decode())

        with mock.patch.object(brain_webhook, "_send", side_effect=capture_send):
            brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path=str(webhooks_dir))

        assert "text" in captured_payload["data"]
        assert "blocks" in captured_payload["data"]


# ---------------------------------------------------------------------------
# Secrets / token leakage tests
# ---------------------------------------------------------------------------

class TestNoSecretLeakInLogs:
    """Verify that Telegram bot tokens never appear in stderr output."""

    REAL_TOKEN = "987654321:ABCdefGHIjklMNOpqrSTUvwxyz012345"

    def test_token_not_in_stderr_on_delivery_failure(self, webhooks_dir, capsys):
        url = f"https://api.telegram.org/bot{self.REAL_TOKEN}/sendMessage"
        cfg = {
            "task_done": [
                {
                    "type": "telegram",
                    "url": url,
                    "chat_id": "-1001234567890",
                    "enabled": True,
                }
            ]
        }
        _write_webhooks_cfg(webhooks_dir, cfg)

        with mock.patch.object(
            brain_webhook, "_send", side_effect=OSError("connection refused")
        ):
            brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path=str(webhooks_dir))

        captured = capsys.readouterr()
        assert self.REAL_TOKEN not in captured.err, (
            f"Token leaked into stderr!\nstderr: {captured.err!r}"
        )
        assert "bot***" in captured.err

    def test_token_not_in_stderr_on_url_validation_failure(self, webhooks_dir, capsys):
        # Use a private-IP URL that contains a token-like string in a path
        url = f"http://192.168.0.1/bot{self.REAL_TOKEN}/sendMessage"
        cfg = {
            "task_done": [
                {
                    "type": "telegram",
                    "url": url,
                    "chat_id": "-1001234567890",
                    "enabled": True,
                }
            ]
        }
        _write_webhooks_cfg(webhooks_dir, cfg)

        with mock.patch.object(brain_webhook, "_send") as mock_send:
            brain_webhook.fire_task_done(SAMPLE_EVENT, brain_path=str(webhooks_dir))

        captured = capsys.readouterr()
        assert self.REAL_TOKEN not in captured.err, (
            f"Token leaked into stderr!\nstderr: {captured.err!r}"
        )
        mock_send.assert_not_called()

    def test_mask_token_covers_all_formats(self):
        """Ensure mask_token handles various token formats."""
        tokens = [
            "bot123456789:ABCdefGHI_jklMNO-pqrSTUvwxyz",
            "bot000000000:a",
            "bot9999999:ZZZZ",
        ]
        for token in tokens:
            assert self.REAL_TOKEN not in brain_webhook.mask_token(f"prefix-{token}-suffix")
            assert "bot***" in brain_webhook.mask_token(token)
