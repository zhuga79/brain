"""Unit tests for brain_wiki frontmatter module.

Tests: parse_frontmatter, format_frontmatter, as_bool, as_list.
"""
import pytest
from brain_wiki import (
    FrontmatterError,
    as_bool,
    as_list,
    format_frontmatter,
    parse_frontmatter,
)


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

    @pytest.mark.parametrize("alias,expected", [
        ("yes", True), ("Yes", True), ("YES", True),
        ("no", False), ("No", False), ("NO", False),
        ("on", True), ("On", True), ("ON", True),
        ("off", False), ("Off", False), ("OFF", False),
    ])
    def test_yaml11_boolean_aliases(self, alias, expected):
        """YAML 1.1 aliases must read as bools, exactly like a real YAML 1.1
        parser (pyyaml SafeLoader) resolves them."""
        fm, _ = parse_frontmatter(f"---\nenabled: {alias}\n---\n")
        assert fm["enabled"] is expected

    def test_yaml11_boolean_aliases_inside_flow_list(self):
        fm, _ = parse_frontmatter("---\nflags: [on, off, yes, no]\n---\n")
        assert fm["flags"] == [True, False, True, False]

    def test_yaml11_aliases_in_block_list(self):
        fm, _ = parse_frontmatter("---\nflags:\n  - on\n  - no\n---\n")
        assert fm["flags"] == [True, False]

    def test_yaml11_words_stay_strings_when_quoted(self):
        """Quoted aliases are strings, not bools — on the write side they are
        quoted precisely so a real parser keeps them as strings."""
        fm, _ = parse_frontmatter('---\nstatus: "yes"\n---\n')
        assert fm["status"] == "yes"
        assert fm["status"] is not True

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


class TestQuotingRegression:
    """The bug this module exists to fix: a colon in a plain scalar value
    used to be written unescaped, which produces a document that looks like
    YAML but breaks under a real YAML parser (`mapping values are not
    allowed here`) and that a hand-written canonical YAML file (quoted or
    block-list) used to be misread by the old split(':', 1) reader."""

    def test_colon_in_value_is_quoted_on_write(self):
        text = format_frontmatter({"title": "Разбор: что дальше"}, "")
        line = next(l for l in text.splitlines() if l.startswith("title:"))
        assert line == 'title: "Разбор: что дальше"'

    def test_colon_in_value_roundtrips(self):
        original = {"title": "Разбор: что дальше"}
        text = format_frontmatter(original, "body\n")
        fm, _ = parse_frontmatter(text)
        assert fm["title"] == "Разбор: что дальше"

    def test_description_with_colon_like_skill_incident(self):
        """Regression for the laravel-verification/SKILL.md incident: an
        unquoted colon in `description` used to collapse the whole
        frontmatter block silently."""
        original = {
            "name": "laravel-verification",
            "description": "Verify Laravel code: routes, migrations, tests",
            "model": "sonnet",
        }
        text = format_frontmatter(original, "")
        fm, _ = parse_frontmatter(text)
        assert fm["name"] == "laravel-verification"
        assert fm["description"] == "Verify Laravel code: routes, migrations, tests"
        assert fm["model"] == "sonnet"

    def test_double_quote_in_value_roundtrips(self):
        original = {"title": 'He said "hi"'}
        text = format_frontmatter(original, "")
        fm, _ = parse_frontmatter(text)
        assert fm["title"] == 'He said "hi"'

    def test_newline_in_value_roundtrips(self):
        original = {"note": "line one\nline two"}
        text = format_frontmatter(original, "")
        fm, _ = parse_frontmatter(text)
        assert fm["note"] == "line one\nline two"

    def test_unicode_value_roundtrips(self):
        original = {"title": "Отчёт по делу — заключение 🎯"}
        text = format_frontmatter(original, "")
        fm, _ = parse_frontmatter(text)
        assert fm["title"] == "Отчёт по делу — заключение 🎯"

    def test_backslash_in_value_roundtrips(self):
        original = {"path": "C:\\Users\\test"}
        text = format_frontmatter(original, "")
        fm, _ = parse_frontmatter(text)
        assert fm["path"] == "C:\\Users\\test"

    def test_list_item_with_colon_roundtrips(self):
        original = {"tags": ["note: important", "plain"]}
        text = format_frontmatter(original, "")
        fm, _ = parse_frontmatter(text)
        assert fm["tags"] == ["note: important", "plain"]

    def test_leading_dash_value_is_quoted(self):
        """A value starting with '-' is ambiguous with a block-sequence
        marker; must be quoted so a real parser doesn't choke on it."""
        text = format_frontmatter({"title": "- bullet-like"}, "")
        fm, _ = parse_frontmatter(text)
        assert fm["title"] == "- bullet-like"

    def test_numeric_looking_string_stays_a_string(self):
        text = format_frontmatter({"code": "007"}, "")
        fm, _ = parse_frontmatter(text)
        assert fm["code"] == "007"

    @pytest.mark.parametrize("word", ["true", "yes", "no", "on", "off"])
    def test_reserved_word_string_stays_a_string(self, word):
        text = format_frontmatter({"status": word}, "")
        fm, _ = parse_frontmatter(text)
        assert fm["status"] == word
        assert fm["status"] is not True


class TestBlockListsCanonicalYaml:
    """Canonical YAML block sequences must be read, not silently dropped.
    Absorbs the block-list-parsing part of
    t-2026-08-17-wiki-frontmatter-parser-narrow."""

    def test_block_list_is_parsed(self):
        text = "---\nsources:\n  - raw/a.md\n  - raw/b.md\n---\nbody\n"
        fm, body = parse_frontmatter(text)
        assert fm["sources"] == ["raw/a.md", "raw/b.md"]
        assert body == "body\n"

    def test_block_list_with_quoted_items(self):
        text = '---\ntags:\n  - "with: colon"\n  - plain\n---\n'
        fm, _ = parse_frontmatter(text)
        assert fm["tags"] == ["with: colon", "plain"]

    def test_block_list_mixed_with_scalar_keys(self):
        text = "---\ntitle: X\nrelated:\n  - a\n  - b\ntype: concept\n---\n"
        fm, _ = parse_frontmatter(text)
        assert fm["title"] == "X"
        assert fm["related"] == ["a", "b"]
        assert fm["type"] == "concept"

    def test_bare_key_with_no_items_is_null(self):
        text = "---\ntags:\ntitle: X\n---\n"
        fm, _ = parse_frontmatter(text)
        assert fm["tags"] is None
        assert fm["title"] == "X"


class TestFrontmatterErrorsOnUnsupportedYaml:
    """Constructs outside the supported subset must raise, not silently
    return an empty value."""

    def test_block_scalar_literal_raises(self):
        text = "---\nnote: |\n  multi\n  line\n---\n"
        with pytest.raises(FrontmatterError):
            parse_frontmatter(text)

    def test_flow_mapping_raises(self):
        text = "---\nmeta: {a: 1}\n---\n"
        with pytest.raises(FrontmatterError):
            parse_frontmatter(text)

    def test_unexpected_indent_raises(self):
        text = "---\n  title: X\n---\n"
        with pytest.raises(FrontmatterError):
            parse_frontmatter(text)

    def test_line_without_colon_raises(self):
        text = "---\njust text here\n---\n"
        with pytest.raises(FrontmatterError):
            parse_frontmatter(text)

    def test_anchor_raises(self):
        text = "---\ntitle: &anchor X\n---\n"
        with pytest.raises(FrontmatterError):
            parse_frontmatter(text)


class TestRealYamlCompat:
    """Anything format_frontmatter writes must parse identically under a
    real YAML parser. pyyaml is a test-only dependency (see
    .github/workflows/tests.yml) — brain-runtime itself stays
    dependency-free, per pyproject.toml."""

    yaml = pytest.importorskip("yaml")

    def _load_frontmatter_block(self, text: str):
        assert text.startswith("---\n")
        end = text.index("\n---", 4)
        block = text[4:end]
        return self.yaml.safe_load(block)

    @pytest.mark.parametrize("value", [
        "Разбор: что дальше",
        "plain value",
        'quote " inside',
        "line one\nline two",
        "Отчёт — заключение 🎯",
        "C:\\Users\\test",
        "- looks like a list item",
        "007",
        "true",
        "yes",
        "off",
        "",
        "trailing colon:",
    ])
    def test_scalar_survives_real_yaml_parser(self, value):
        text = format_frontmatter({"field": value}, "")
        parsed = self._load_frontmatter_block(text)
        assert parsed["field"] == value

    def test_list_survives_real_yaml_parser(self):
        original = ["a", "note: important", "b, c"]
        text = format_frontmatter({"tags": original}, "")
        parsed = self._load_frontmatter_block(text)
        assert parsed["tags"] == original

    def test_bool_survives_real_yaml_parser(self):
        text = format_frontmatter({"protected": True, "draft": False}, "")
        parsed = self._load_frontmatter_block(text)
        assert parsed["protected"] is True
        assert parsed["draft"] is False

    @pytest.mark.parametrize("alias,expected", [
        ("yes", True), ("no", False), ("on", True), ("off", False),
        ("Yes", True), ("NO", False), ("ON", True), ("Off", False),
    ])
    def test_yaml11_alias_reads_match_real_parser(self, alias, expected):
        """The reader must resolve YAML 1.1 boolean aliases to the same value
        a real YAML 1.1 parser produces for the same hand-written block."""
        text = f"---\nenabled: {alias}\n---\n"
        fm, _ = parse_frontmatter(text)
        real = self.yaml.safe_load(f"enabled: {alias}\n")["enabled"]
        assert fm["enabled"] == real == expected

    def test_yaml11_string_words_roundtrip_under_real_parser(self):
        """Strings that collide with YAML 1.1 bool words must survive our
        writer as quoted strings and read back as strings, under pyyaml."""
        for word in ("yes", "no", "on", "off", "true", "false"):
            text = format_frontmatter({"status": word}, "")
            parsed = self._load_frontmatter_block(text)
            assert parsed["status"] == word
            assert parsed["status"] is not True
            fm, _ = parse_frontmatter(text)
            assert fm["status"] == word

    def test_full_document_parses_as_valid_yaml(self):
        fm = {
            "title": "Разбор: что дальше",
            "type": "concept",
            "tags": ["a", "b: c"],
            "protected": True,
        }
        text = format_frontmatter(fm, "body\n")
        parsed = self._load_frontmatter_block(text)
        assert parsed == fm
