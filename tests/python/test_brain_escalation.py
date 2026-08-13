"""Tests for brain_wiki/escalation.py — the dependency-free matrix parser."""

from __future__ import annotations

import pytest
from pathlib import Path

from brain_wiki.escalation import (
    EscalationParseError,
    load_escalation_matrix,
    parse_document,
)


def _sample_yaml() -> str:
    return """\
# Escalation matrix sample
version: 1
updated: 2026-08-11

zones:
  - id: contract-text
    name: Текст договора, оферты, устава
    primary: [lawyer]
    escalate: [compliance, tax-advisor]
    note: "lawyer — после, cfo — структура"
  - id: code-quality
    name: Качество кода
    primary: [reviewer]
    escalate: [architect]

tax_stages:
  - id: tax-stage-4b
    name: Этап 4b — Возражения на акт
    primary: [lawyer, tax-advisor]
    escalate: []
"""


class TestParseDocument:
    def test_parses_sample(self):
        data = parse_document(_sample_yaml())
        assert data["version"] == 1
        assert data["updated"] == "2026-08-11"
        assert [z["id"] for z in data["zones"]] == ["contract-text", "code-quality"]
        assert data["zones"][0]["primary"] == ["lawyer"]
        assert data["zones"][0]["escalate"] == ["compliance", "tax-advisor"]
        assert data["zones"][0]["name"] == "Текст договора, оферты, устава"
        assert data["zones"][0]["note"] == "lawyer — после, cfo — структура"
        assert data["tax_stages"][0]["primary"] == ["lawyer", "tax-advisor"]
        assert data["tax_stages"][0]["escalate"] == []

    def test_empty_document(self):
        assert parse_document("# only comments\n") == {}

    def test_quoted_scalar_unquoted(self):
        data = parse_document("name: 'quoted value'\n")
        assert data["name"] == "quoted value"

    def test_quoted_scalar_double_quotes(self):
        data = parse_document('name: "double value"\n')
        assert data["name"] == "double value"

    def test_bool_scalars(self):
        data = parse_document("a: true\nb: false\n")
        assert data == {"a": True, "b": False}

    def test_inline_list_with_quotes(self):
        data = parse_document("roles: ['a', \"b\", c]\n")
        assert data["roles"] == ["a", "b", "c"]

    def test_empty_inline_list(self):
        data = parse_document("escalate: []\n")
        assert data["escalate"] == []

    def test_block_list_requires_item_pairs(self):
        data = parse_document(
            "zones:\n  - id: a\n    name: Zone A\n"
        )
        assert data["zones"] == [{"id": "a", "name": "Zone A"}]

    def test_item_after_item_keeps_appending(self):
        data = parse_document(
            "zones:\n  - id: a\n  - id: b\n"
        )
        assert data["zones"] == [{"id": "a"}, {"id": "b"}]

    def test_item_outside_list_errors(self):
        with pytest.raises(EscalationParseError):
            parse_document("  - id: a\n")

    def test_bad_top_level_line_errors(self):
        with pytest.raises(EscalationParseError):
            parse_document("just text without colon\n")

    def test_nested_without_item_errors(self):
        with pytest.raises(EscalationParseError):
            parse_document("zones:\n    name: no item\n")

    def test_empty_key_errors(self):
        with pytest.raises(EscalationParseError):
            parse_document(": value\n")

    def test_item_without_pair_errors(self):
        with pytest.raises(EscalationParseError):
            parse_document("zones:\n  - just text\n")


class TestLoadEscalationMatrix:
    def test_missing_file_returns_none_no_errors(self, tmp_path: Path):
        data, errors = load_escalation_matrix(tmp_path)
        assert data is None
        assert errors == []

    def test_loads_valid_file(self, tmp_path: Path):
        (tmp_path / "doctrine").mkdir()
        (tmp_path / "doctrine" / "escalation-matrix.yaml").write_text(_sample_yaml())
        data, errors = load_escalation_matrix(tmp_path)
        assert errors == []
        assert data is not None
        assert len(data["zones"]) == 2

    def test_parse_error_returned_in_errors(self, tmp_path: Path):
        (tmp_path / "doctrine").mkdir()
        (tmp_path / "doctrine" / "escalation-matrix.yaml").write_text(
            "zones:\n    name: no item\n"
        )
        data, errors = load_escalation_matrix(tmp_path)
        assert data is None
        assert any("вне элемента списка" in e for e in errors)

    def test_accepts_string_path(self, tmp_path: Path):
        (tmp_path / "doctrine").mkdir()
        (tmp_path / "doctrine" / "escalation-matrix.yaml").write_text("version: 1\n")
        data, errors = load_escalation_matrix(str(tmp_path))
        assert errors == []
        assert data == {"version": 1}
