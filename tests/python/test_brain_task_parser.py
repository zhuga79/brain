"""Tests for runtime/lib/brain_task_parser.py"""
import pytest
from brain_task_parser import (
    parse_block, find_blocks, find_block, is_done,
    state_from_char, is_valid_priority,
)


class TestParseBlock:
    def test_simple(self):
        block = "- [ ] [P1] t-x — Title\n      role: dev   mode: solo\n"
        info = parse_block(block)
        assert info["state"] == " "
        assert info["prio"] == "P1"
        assert info["id"] == "t-x"
        assert info["title"] == "Title"
        assert info["role"] == "dev"
        assert info["mode"] == "solo"

    def test_with_deps(self):
        block = "- [~] [P0] t-y — Title\n      depends_on: [a, b, c]\n"
        info = parse_block(block)
        assert info["deps"] == ["a", "b", "c"]
        assert info["state"] == "~"

    def test_with_council(self):
        block = "- [ ] [P2] t-z — T\n      council: [arch, reviewer]\n      mode: council\n"
        info = parse_block(block)
        assert info["council"] == ["arch", "reviewer"]
        assert info["mode"] == "council"

    def test_with_parent(self):
        block = "- [ ] [P1] t-child — T\n      parent: t-parent\n"
        info = parse_block(block)
        assert info["parent"] == "t-parent"

    def test_invalid_returns_empty(self):
        assert parse_block("not a task block") == {}

    def test_blocked_state(self):
        block = "- [!] [P0] t-blocked — Urgent\n"
        info = parse_block(block)
        assert info["state"] == "!"
        assert info["prio"] == "P0"

    def test_done_state(self):
        block = "- [x] [P3] t-done — Done task\n"
        info = parse_block(block)
        assert info["state"] == "x"

    def test_acceptance_field(self):
        block = "- [ ] [P1] t-acc — Task\n      acceptance: All tests pass\n"
        info = parse_block(block)
        assert info["acceptance"] == "All tests pass"

    def test_by_and_started_fields(self):
        block = "- [~] [P1] t-run — Running\n      by: agent-1\n      started: 2026-01-01T00:00:00Z\n"
        info = parse_block(block)
        assert info["by"] == "agent-1"
        assert info["started"] == "2026-01-01T00:00:00Z"

    def test_client_and_project_fields(self):
        block = ("- [ ] [P1] t-c — Title\n      role: lawyer   mode: solo\n"
                 "      client: ИП Ромашкин   project: Аренда-складов\n")
        info = parse_block(block)
        assert info["client"] == "ИП Ромашкин"
        assert info["project"] == "Аренда-складов"

    def test_client_project_default_empty(self):
        info = parse_block("- [ ] [P1] t-nc — Task\n      role: developer\n")
        assert info["client"] == ""
        assert info["project"] == ""

    def test_client_with_spaces(self):
        block = "- [ ] [P1] t-cl — T\n      client: ООО «Ромашка и партнёры»\n"
        info = parse_block(block)
        assert info["client"] == "ООО «Ромашка и партнёры»"

    def test_client_project_format_roundtrip(self):
        block = ("- [ ] [P1] t-rt — Title\n      role: developer\n"
                 "      client: ИП Ромашкин\n      project: Аренда-складов\n")
        info = parse_block(block)
        assert info["client"] == "ИП Ромашкин"
        assert info["project"] == "Аренда-складов"
        out = format_block(info)
        reparsed = parse_block(out)
        assert reparsed["client"] == "ИП Ромашкин"
        assert reparsed["project"] == "Аренда-складов"
        assert "client: ИП Ромашкин" in out
        assert "project: Аренда-складов" in out

    def test_raw_field_preserved(self):
        block = "- [ ] [P1] t-raw — Task\n"
        info = parse_block(block)
        assert info["raw"] == block

    def test_empty_deps_by_default(self):
        block = "- [ ] [P1] t-nodeps — Task\n"
        info = parse_block(block)
        assert info["deps"] == []

    def test_empty_council_by_default(self):
        block = "- [ ] [P1] t-nocouncil — Task\n"
        info = parse_block(block)
        assert info["council"] == []


class TestFindBlocks:
    def test_extract_multiple(self):
        text = (
            "## P1\n\n"
            "- [ ] [P1] t-a — A\n      role: dev\n\n"
            "- [x] [P0] t-b — B\n      by: agent\n"
        )
        blocks = find_blocks(text)
        assert len(blocks) == 2

    def test_extract_none_from_empty(self):
        assert find_blocks("") == []

    def test_extract_none_from_non_task(self):
        assert find_blocks("# Just a heading\n\nSome text\n") == []

    def test_single_block(self):
        text = "- [ ] [P2] t-one — Single\n      role: dev\n"
        blocks = find_blocks(text)
        assert len(blocks) == 1
        assert "t-one" in blocks[0]


class TestFindBlock:
    def test_finds_by_id(self):
        text = "- [ ] [P1] t-abc — Task A\n- [x] [P2] t-xyz — Task B\n"
        result = find_block(text, "t-abc")
        assert result is not None
        assert "t-abc" in result

    def test_returns_none_for_missing(self):
        text = "- [ ] [P1] t-abc — Task A\n"
        assert find_block(text, "t-missing") is None

    def test_exact_id_match(self):
        # t-ab should not match t-abc
        text = "- [ ] [P1] t-abc — Task A\n"
        result = find_block(text, "t-ab")
        assert result is None


class TestIsDone:
    def test_done_task(self):
        text = "- [x] [P1] t-x — Title\n"
        assert is_done(text, "t-x")

    def test_open_task(self):
        text = "- [ ] [P1] t-x — Title\n"
        assert not is_done(text, "t-x")

    def test_missing_task(self):
        assert not is_done("", "t-x")

    def test_in_progress_not_done(self):
        text = "- [~] [P1] t-x — Title\n"
        assert not is_done(text, "t-x")

    def test_blocked_not_done(self):
        text = "- [!] [P1] t-x — Title\n"
        assert not is_done(text, "t-x")


class TestStateFromChar:
    @pytest.mark.parametrize("ch,expected", [
        (" ", "open"), ("~", "in_progress"),
        ("x", "done"), ("!", "blocked"),
        ("?", "unknown"),
    ])
    def test_states(self, ch, expected):
        assert state_from_char(ch) == expected

    def test_unknown_char(self):
        assert state_from_char("z") == "unknown"

    def test_empty_string(self):
        assert state_from_char("") == "unknown"


class TestIsValidPriority:
    @pytest.mark.parametrize("p,ok", [
        ("P0", True), ("P1", True), ("P2", True), ("P3", True),
        ("P4", False), ("p1", False), ("", False),
    ])
    def test_priority(self, p, ok):
        assert is_valid_priority(p) is ok

    def test_numeric_invalid(self):
        assert not is_valid_priority("1")

    def test_p_only_invalid(self):
        assert not is_valid_priority("P")


# --- t-2026-06-26-orchestrator-route: surface/gate routing ---
from brain_task_parser import effective_surface, format_block


class TestSurfaceGate:
    def test_parse_explicit_surface_and_gate(self):
        block = ("- [ ] [P1] t-s — Title\n      role: developer   mode: solo\n"
                 "      surface: interactive   gate: approval\n")
        info = parse_block(block)
        assert info["surface"] == "interactive"
        assert info["gate"] == "approval"

    def test_default_surface_headless(self):
        info = parse_block("- [ ] [P1] t-h — T\n      role: developer\n")
        assert info["surface"] == ""          # not explicitly set
        assert effective_surface(info) == "headless"

    def test_explicit_interactive_wins(self):
        info = parse_block("- [ ] [P1] t-i — T\n      role: developer\n      surface: interactive\n")
        assert effective_surface(info) == "interactive"

    def test_gate_implies_interactive(self):
        info = parse_block("- [ ] [P1] t-g — T\n      role: developer\n      gate: taste\n")
        assert effective_surface(info) == "interactive"

    def test_role_inference_taste_reviewer(self):
        info = parse_block("- [ ] [P1] t-r — T\n      role: taste-reviewer\n")
        assert effective_surface(info) == "interactive"

    def test_role_inference_lawyer(self):
        info = parse_block("- [ ] [P1] t-l — T\n      role: lawyer\n")
        assert effective_surface(info) == "interactive"

    def test_explicit_headless_overrides_role(self):
        info = parse_block("- [ ] [P1] t-o — T\n      role: lawyer\n      surface: headless\n")
        assert effective_surface(info) == "headless"

    def test_format_block_roundtrips_surface_gate(self):
        block = ("- [ ] [P1] t-rt — Title\n      role: developer\n"
                 "      surface: interactive\n      gate: legal\n")
        info = parse_block(block)
        out = format_block(info)
        assert "surface: interactive" in out
        assert "gate: legal" in out
