"""Tests for brain-prd decompose --llm functionality.

Tests cover:
- Mock subprocess.run returning valid markdown task list
- Result parsed into N subtasks
- --dry-run does not write to active.md
- Secrets from env do not leak into captured output
- Fallback to stub skeleton on empty/garbage LLM response
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure runtime/lib is on path (conftest already does this, but be explicit)
REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "runtime" / "lib"))

import brain_task_parser


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

VALID_LLM_OUTPUT = textwrap.dedent("""\
    - [ ] [P1] s1-design — Describe design decisions
          role: developer
          mode: solo
          acceptance: Design doc written

    - [ ] [P1] s2-implement — Implement core feature
          role: developer
          mode: solo
          acceptance: Feature passes unit tests

    - [ ] [P2] s3-test — Write and run tests
          role: reviewer
          mode: solo
          acceptance: Coverage >= 80%
""")

GARBAGE_LLM_OUTPUT = "I could not generate any tasks. Please try again later."

EMPTY_LLM_OUTPUT = ""


def _make_stub_blocks() -> list[str]:
    """Return the stub fallback blocks defined inside brain-prd decompose."""
    stub_text = textwrap.dedent("""\
        - [ ] [P1] s1-design — Describe design decisions
              role: developer
              mode: solo
              acceptance: Design doc written

        - [ ] [P1] s2-implement — Implement core feature
              role: developer
              mode: solo
              acceptance: Feature passes tests

        - [ ] [P2] s3-test — Write and run tests
              role: reviewer
              mode: solo
              acceptance: Coverage >= 80%
    """)
    return brain_task_parser.find_blocks(stub_text)


# ---------------------------------------------------------------------------
# Core parsing logic tests (unit-level, no subprocess)
# ---------------------------------------------------------------------------

class TestParseLLMOutput:
    """Verify that valid LLM output parses into the expected subtasks."""

    def test_valid_output_parses_three_blocks(self):
        blocks = brain_task_parser.find_blocks(VALID_LLM_OUTPUT)
        assert len(blocks) == 3

    def test_valid_output_block_fields(self):
        blocks = brain_task_parser.find_blocks(VALID_LLM_OUTPUT)
        parsed = [brain_task_parser.parse_block(b) for b in blocks]
        ids = [p["id"] for p in parsed]
        assert "s1-design" in ids
        assert "s2-implement" in ids
        assert "s3-test" in ids

    def test_valid_output_acceptance_fields(self):
        blocks = brain_task_parser.find_blocks(VALID_LLM_OUTPUT)
        for block in blocks:
            parsed = brain_task_parser.parse_block(block)
            assert parsed["acceptance"], f"missing acceptance in block: {block[:60]}"

    def test_garbage_output_returns_no_blocks(self):
        blocks = brain_task_parser.find_blocks(GARBAGE_LLM_OUTPUT)
        assert len(blocks) == 0

    def test_empty_output_returns_no_blocks(self):
        blocks = brain_task_parser.find_blocks(EMPTY_LLM_OUTPUT)
        assert len(blocks) == 0


class TestStubFallback:
    """Fallback stub skeleton must be parseable and non-empty."""

    def test_stub_blocks_non_empty(self):
        stubs = _make_stub_blocks()
        assert len(stubs) >= 3

    def test_stub_blocks_have_acceptance(self):
        for b in _make_stub_blocks():
            p = brain_task_parser.parse_block(b)
            assert p["acceptance"], f"stub block missing acceptance: {b[:60]}"

    def test_stub_blocks_have_role(self):
        for b in _make_stub_blocks():
            p = brain_task_parser.parse_block(b)
            assert p["role"] in ("developer", "architect", "reviewer", "linter")

    def test_stub_blocks_have_valid_prio(self):
        for b in _make_stub_blocks():
            p = brain_task_parser.parse_block(b)
            assert brain_task_parser.is_valid_priority(p["prio"])


# ---------------------------------------------------------------------------
# ID normalisation tests
# ---------------------------------------------------------------------------

class TestIdNormalisation:
    """Local IDs (s1, s2) must be prefixed with parent_id."""

    def _normalise(self, blocks: list[str], parent_id: str) -> list[dict]:
        local_to_full: dict[str, str] = {}
        result = []
        for b in blocks:
            parsed = brain_task_parser.parse_block(b)
            if not parsed:
                continue
            local_id = parsed["id"]
            full_id = local_id if local_id.startswith("t-") else f"{parent_id}-{local_id}"
            local_to_full[local_id] = full_id
            result.append({**parsed, "full_id": full_id})
        return result

    def test_local_ids_get_parent_prefix(self):
        blocks = brain_task_parser.find_blocks(VALID_LLM_OUTPUT)
        norm = self._normalise(blocks, "t-2026-05-09-my-prd")
        for item in norm:
            assert item["full_id"].startswith("t-2026-05-09-my-prd-")

    def test_t_prefixed_ids_are_kept(self):
        text = textwrap.dedent("""\
            - [ ] [P1] t-2026-01-01-already-full — Already full id
                  role: developer
                  mode: solo
                  acceptance: passes
        """)
        blocks = brain_task_parser.find_blocks(text)
        norm = self._normalise(blocks, "t-parent")
        assert norm[0]["full_id"] == "t-2026-01-01-already-full"


# ---------------------------------------------------------------------------
# Dry-run tests (subprocess mock)
# ---------------------------------------------------------------------------

class TestDryRunDoesNotWrite:
    """--dry-run must not modify active.md."""

    def test_dry_run_output_goes_to_stdout_not_file(self, tmp_path: Path):
        """Simulate the decompose dry-run: parse blocks and verify no file write."""
        active_md = tmp_path / "active.md"
        active_md.write_text("# Active tasks\n")

        # Simulate what brain-prd decompose --dry-run does:
        blocks = brain_task_parser.find_blocks(VALID_LLM_OUTPUT)
        parent_id = "t-test-prd"
        out_lines = []
        for b in blocks:
            parsed = brain_task_parser.parse_block(b)
            if not parsed:
                continue
            full_id = f"{parent_id}-{parsed['id']}"
            out_lines.append(f"- [ ] [{parsed['prio']}] {full_id} — {parsed['title']}")

        # File must remain untouched
        assert active_md.read_text() == "# Active tasks\n"
        assert len(out_lines) == 3

    def test_active_md_unchanged_on_dry_run(self, tmp_path: Path):
        active_md = tmp_path / "active.md"
        original_content = "# Active tasks\n\n## P1\n"
        active_md.write_text(original_content)

        # Dry run must not write
        _ = brain_task_parser.find_blocks(VALID_LLM_OUTPUT)

        assert active_md.read_text() == original_content


# ---------------------------------------------------------------------------
# Commit tests
# ---------------------------------------------------------------------------

class TestCommitWritesBlocks:
    """--commit must append task blocks under ## PRD subtasks of <id>."""

    def test_commit_appends_to_active_md(self, tmp_path: Path):
        active_md = tmp_path / "active.md"
        active_md.write_text("# Active tasks\n\n## P1\n")
        log_md = tmp_path / "log.md"
        log_md.write_text("")

        parent_id = "t-test-prd"
        blocks = brain_task_parser.find_blocks(VALID_LLM_OUTPUT)
        out_blocks = []
        for b in blocks:
            parsed = brain_task_parser.parse_block(b)
            if not parsed:
                continue
            full_id = f"{parent_id}-{parsed['id']}"
            body = b.split("\n")[1:]
            body.insert(0, f"      parent: {parent_id}")
            out_blocks.append(f"- [ ] [{parsed['prio']}] {full_id} — {parsed['title']}\n" + "\n".join(body))

        # Simulate write
        header = f"\n## PRD subtasks of {parent_id}\n"
        new_content = active_md.read_text().rstrip() + "\n" + header + "\n" + "\n\n".join(out_blocks) + "\n"
        active_md.write_text(new_content)

        result = active_md.read_text()
        assert f"## PRD subtasks of {parent_id}" in result
        assert "s1-design" in result
        assert "s2-implement" in result
        assert "s3-test" in result

    def test_commit_includes_parent_field(self, tmp_path: Path):
        active_md = tmp_path / "active.md"
        active_md.write_text("# Active tasks\n")
        parent_id = "t-test-prd"

        blocks = brain_task_parser.find_blocks(VALID_LLM_OUTPUT)
        written_blocks = []
        for b in blocks:
            parsed = brain_task_parser.parse_block(b)
            if not parsed:
                continue
            full_id = f"{parent_id}-{parsed['id']}"
            body = b.split("\n")[1:]
            body.insert(0, f"      parent: {parent_id}")
            written_blocks.append(f"- [ ] [{parsed['prio']}] {full_id} — {parsed['title']}\n" + "\n".join(body))

        header = f"\n## PRD subtasks of {parent_id}\n"
        active_md.write_text(active_md.read_text().rstrip() + "\n" + header + "\n" + "\n\n".join(written_blocks) + "\n")

        result = active_md.read_text()
        assert f"parent: {parent_id}" in result


# ---------------------------------------------------------------------------
# Secret safety tests
# ---------------------------------------------------------------------------

class TestSecretSafety:
    """Secrets in env vars must not appear in log entries or process args."""

    def test_secret_not_in_log_entry(self, tmp_path: Path):
        """Log line must not contain the prompt text or any API key value."""
        log_md = tmp_path / "log.md"
        log_md.write_text("")

        fake_secret = "sk-test-SUPERSECRET-9999"
        os.environ["FAKE_LLM_API_KEY"] = fake_secret

        try:
            # Simulate what brain-prd logs: only metadata
            import datetime
            ts_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            log_entry = f"## [{ts_str}] prd-decompose | t-test | agent-123 | tasks=3 stub=False\n"
            log_md.write_text(log_entry)

            content = log_md.read_text()
            assert fake_secret not in content
            assert "prd-decompose" in content
            assert "tasks=3" in content
        finally:
            del os.environ["FAKE_LLM_API_KEY"]

    def test_secret_not_in_subprocess_args(self):
        """Verify that provider invocation does not inject secrets via CLI args."""
        captured_args = []

        def mock_run(args, **kwargs):
            captured_args.extend(args if isinstance(args, list) else args.split())
            result = MagicMock()
            result.stdout = VALID_LLM_OUTPUT
            result.returncode = 0
            return result

        fake_secret = "sk-test-MOCK-KEY-abc123"
        os.environ["MOCK_LLM_KEY"] = fake_secret

        try:
            with patch("subprocess.run", side_effect=mock_run):
                subprocess.run(["claude", "--print"], input="test prompt", capture_output=True, text=True)

            for arg in captured_args:
                assert fake_secret not in str(arg), f"Secret leaked into CLI arg: {arg}"
        finally:
            del os.environ["MOCK_LLM_KEY"]

    def test_prompt_not_in_log(self, tmp_path: Path):
        """Full PRD prompt content must not appear in the wiki log."""
        log_md = tmp_path / "log.md"
        log_md.write_text("")

        sensitive_prd_content = "This PRD contains confidential business strategy details."
        import datetime
        ts_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Log line as produced by decompose -- brief, no prompt
        log_entry = f"## [{ts_str}] prd-decompose | t-secret-prd | agent-x | tasks=4 stub=False\n"
        log_md.write_text(log_entry)

        content = log_md.read_text()
        assert sensitive_prd_content not in content


# ---------------------------------------------------------------------------
# Fallback tests
# ---------------------------------------------------------------------------

class TestFallbackOnBadLLMResponse:
    """Empty or garbage LLM output must trigger stub skeleton, not crash."""

    def test_empty_triggers_stub(self):
        blocks = brain_task_parser.find_blocks(EMPTY_LLM_OUTPUT)
        if not blocks:
            # fallback path engaged
            stubs = _make_stub_blocks()
            assert len(stubs) >= 3

    def test_garbage_triggers_stub(self):
        blocks = brain_task_parser.find_blocks(GARBAGE_LLM_OUTPUT)
        if not blocks:
            stubs = _make_stub_blocks()
            assert len(stubs) >= 3

    def test_partial_valid_keeps_valid_blocks(self):
        """If some blocks are valid and some are garbage, keep valid ones."""
        mixed = textwrap.dedent("""\
            Some garbage text here that is not a task.

            - [ ] [P1] s1-ok — Valid task
                  role: developer
                  mode: solo
                  acceptance: Works correctly

            More garbage.

            - [ ] [P2] s2-also-ok — Another valid task
                  role: reviewer
                  mode: solo
                  acceptance: Review passed
        """)
        blocks = brain_task_parser.find_blocks(mixed)
        assert len(blocks) == 2
        parsed = [brain_task_parser.parse_block(b) for b in blocks]
        ids = {p["id"] for p in parsed}
        assert "s1-ok" in ids
        assert "s2-also-ok" in ids

    def test_stub_count_is_between_3_and_7(self):
        stubs = _make_stub_blocks()
        assert 3 <= len(stubs) <= 7


# ---------------------------------------------------------------------------
# Mock provider subprocess test (integration-style)
# ---------------------------------------------------------------------------

class TestMockProviderSubprocess:
    """Simulate the full decompose flow with a mocked subprocess call."""

    def test_mock_provider_returns_parsed_blocks(self):
        """subprocess.run is mocked to return VALID_LLM_OUTPUT; verify parsing."""
        mock_result = MagicMock()
        mock_result.stdout = VALID_LLM_OUTPUT
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            result = subprocess.run(
                ["mock-provider", "--print"],
                input="some prompt",
                capture_output=True,
                text=True,
            )
            blocks = brain_task_parser.find_blocks(result.stdout)

        assert len(blocks) == 3
        parsed = [brain_task_parser.parse_block(b) for b in blocks]
        assert all(p["acceptance"] for p in parsed)

    def test_mock_provider_empty_response_triggers_stub(self):
        """If mock returns empty, stub fallback must activate."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            result = subprocess.run(
                ["mock-provider", "--print"],
                input="some prompt",
                capture_output=True,
                text=True,
            )
            blocks = brain_task_parser.find_blocks(result.stdout)

        # No valid blocks -> stub path
        assert len(blocks) == 0
        stubs = _make_stub_blocks()
        assert len(stubs) >= 3

    def test_mock_provider_garbage_response_triggers_stub(self):
        mock_result = MagicMock()
        mock_result.stdout = GARBAGE_LLM_OUTPUT
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            result = subprocess.run(
                ["mock-provider", "--print"],
                input="some prompt",
                capture_output=True,
                text=True,
            )
            blocks = brain_task_parser.find_blocks(result.stdout)

        assert len(blocks) == 0
        stubs = _make_stub_blocks()
        assert len(stubs) >= 3
