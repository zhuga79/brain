"""Unit tests for brain_wiki frontmatter module.

Tests: parse_frontmatter, format_frontmatter, as_bool, as_list.
"""
import pytest
from brain_wiki import parse_frontmatter, format_frontmatter, as_bool, as_list


class TestParseFrontmatter:
    """Tests for parse_frontmatter()."""

    def test_empty_input(self):
        fm, body = parse_frontmatter("")
        assert fm == {}
        assert body == ""

    def test_no_frontmatter(self):
        content = "# Heading\nbody"
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_simple_kv(self):
        fm, body = parse_frontmatter("---\ntitle: Hello\n---\nbody\n")
        assert fm == {"title": "Hello"}
        assert body == "body\n"

    def test_value_with_colon(self):
        """Value containing a colon (URL) must not break the parser."""
        fm, _ = parse_frontmatter("---\nurl: https://example.com\n---\n")
        assert fm["url"] == "https://example.com"

    def test_comment_line_skipped(self):
        fm, _ = parse_frontmatter("---\n# this is a comment\ntitle: X\n---\n")
        assert fm == {"title": "X"}

    def test_missing_trailer(self):
        """If the closing --- is absent the content is not treated as frontmatter."""
        fm, body = parse_frontmatter("---\ntitle: X\nbody")
        assert fm == {}
        assert body.startswith("---")

    def test_boolean_values(self):
        fm, _ = parse_frontmatter("---\nprotected: true\ndraft: false\n---\n")
        assert fm["protected"] is True
        assert fm["draft"] is False

    def test_list_value(self):
        fm, _ = parse_frontmatter("---\ntags: [a, b, c]\n---\n")
        assert fm["tags"] == ["a", "b", "c"]

    def test_empty_list(self):
        fm, _ = parse_frontmatter("---\ntags: []\n---\n")
        assert fm["tags"] == []

    def test_body_preserved(self):
        content = "---\ntitle: Test\n---\n# Body\n\nParagraph.\n"
        _, body = parse_frontmatter(content)
        assert "# Body" in body
        assert "Paragraph." in body

    def test_multiple_keys(self):
        text = "---\ntitle: Foo\ntype: concept\ncuration: human\n---\n"
        fm, _ = parse_frontmatter(text)
        assert fm["title"] == "Foo"
        assert fm["type"] == "concept"
        assert fm["curation"] == "human"

    def test_quoted_value(self):
        """Quoted string values should be stripped of quotes."""
        fm, _ = parse_frontmatter('---\ntitle: "Quoted Title"\n---\n')
        assert fm["title"] == "Quoted Title"

    def test_single_quoted_value(self):
        fm, _ = parse_frontmatter("---\ntitle: 'Single Quoted'\n---\n")
        assert fm["title"] == "Single Quoted"


class TestAsBool:
    """Tests for as_bool()."""

    @pytest.mark.parametrize("inp,expected", [
        (True, True),
        (False, False),
        ("y", True),
        ("yes", True),
        ("true", True),
        ("1", True),
        ("Y", True),
        ("YES", True),
        ("True", True),
        ("n", False),
        ("no", False),
        ("false", False),
        ("0", False),
        ("", False),
        ("random", False),
        ("maybe", False),
        (None, False),
    ])
    def test_truthy_falsy(self, inp, expected):
        assert as_bool(inp) is expected

    def test_bool_passthrough_true(self):
        """Native bool True must be returned as-is (no str conversion path)."""
        result = as_bool(True)
        assert result is True
        assert type(result) is bool

    def test_bool_passthrough_false(self):
        result = as_bool(False)
        assert result is False
        assert type(result) is bool


class TestAsList:
    """Tests for as_list()."""

    def test_none(self):
        assert as_list(None) == []

    def test_empty_string(self):
        assert as_list("") == []

    def test_single_string(self):
        assert as_list("foo") == ["foo"]

    def test_list_passthrough(self):
        assert as_list(["a", "b"]) == ["a", "b"]

    def test_strips_whitespace(self):
        assert as_list("  foo  ") == ["foo"]

    def test_list_strips_each_item(self):
        assert as_list(["  a  ", "  b  "]) == ["a", "b"]

    def test_list_drops_empty_after_strip(self):
        """Items that become empty after stripping are dropped."""
        assert as_list(["a", "   ", "b"]) == ["a", "b"]

    def test_numeric_value_coerced_to_str(self):
        """Non-string, non-list values get str() coercion."""
        assert as_list(42) == ["42"]


class TestFormatFrontmatter:
    """Tests for format_frontmatter()."""

    def test_roundtrip_simple(self):
        original_fm = {"title": "Hello World"}
        text = format_frontmatter(original_fm, "body content\n")
        fm, body = parse_frontmatter(text)
        assert fm["title"] == "Hello World"
        assert "body content" in body

    def test_roundtrip_with_list(self):
        original_fm = {"title": "Test", "tags": ["x", "y"]}
        text = format_frontmatter(original_fm, "body\n")
        assert "tags:" in text
        fm, _ = parse_frontmatter(text)
        assert fm["title"] == "Test"

    def test_output_starts_with_dashes(self):
        text = format_frontmatter({"title": "T"}, "body\n")
        assert text.startswith("---\n")

    def test_output_ends_with_newline(self):
        text = format_frontmatter({"title": "T"}, "body")
        assert text.endswith("\n")

    def test_preferred_key_ordering(self):
        """'title' should appear before other keys."""
        fm = {"type": "concept", "title": "First"}
        text = format_frontmatter(fm, "")
        lines = text.split("\n")
        title_idx = next(i for i, l in enumerate(lines) if l.startswith("title:"))
        type_idx = next(i for i, l in enumerate(lines) if l.startswith("type:"))
        assert title_idx < type_idx

    def test_bool_written_lowercase(self):
        text = format_frontmatter({"protected": True}, "")
        assert "protected: true" in text

    def test_empty_body(self):
        text = format_frontmatter({"title": "T"}, "")
        fm, body = parse_frontmatter(text)
        assert fm["title"] == "T"
