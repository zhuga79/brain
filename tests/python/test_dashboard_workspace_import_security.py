import importlib.machinery
import importlib.util
import sys

import pytest


loader = importlib.machinery.SourceFileLoader("brain_dashboard_cli", "runtime/bin/brain-dashboard")
spec = importlib.util.spec_from_loader("brain_dashboard_cli", loader)
brain_dashboard_cli = importlib.util.module_from_spec(spec)
sys.modules["brain_dashboard_cli"] = brain_dashboard_cli
loader.exec_module(brain_dashboard_cli)


class _Response:
    def __init__(self, body: bytes):
        self._body = body

    def read(self, size: int) -> bytes:
        return self._body[:size]


def test_workspace_descriptor_redirect_to_loopback_is_rejected():
    handler = brain_dashboard_cli._SafeDescriptorRedirectHandler()

    with pytest.raises(ValueError, match="redirect URL rejected"):
        handler.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1/descriptor.json")


def test_workspace_descriptor_response_size_is_bounded():
    response = _Response(b"x" * 12)

    with pytest.raises(ValueError, match="descriptor too large"):
        brain_dashboard_cli._read_response_text_bounded(response, max_bytes=10)


def test_workspace_descriptor_response_under_limit_decodes_text():
    response = _Response("проект".encode("utf-8"))

    assert brain_dashboard_cli._read_response_text_bounded(response, max_bytes=128) == "проект"
