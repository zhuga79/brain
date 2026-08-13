"""Tests for runtime/lib/brain_wiki/writers.py — Phase 16 T8.

Target: coverage of brain_wiki/writers >= 40%.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from brain_wiki import (
    Issue,
    append_log,
    lock_issues,
    obsidian_sync_report,
    render_index,
    write_raw_source,
    write_wiki_page,
)
from brain_wiki.writers import PAGE_TYPE_LABELS, OBSIDIAN_EXPECTED_VIEWS, lint_wiki


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_brain(tmp_path: Path) -> Path:
    """Minimal Brain directory structure."""
    for d in ("raw", "wiki", "tasks", ".locks"):
        (tmp_path / d).mkdir()
    (tmp_path / "wiki" / "log.md").write_text("# Log\n\n", encoding="utf-8")
    (tmp_path / "tasks" / "active.md").write_text("", encoding="utf-8")
    (tmp_path / "tasks" / "done.md").write_text("", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# append_log
# ---------------------------------------------------------------------------

class TestAppendLog:
    def test_appends_line_with_all_fields(self, temp_brain: Path) -> None:
        append_log(temp_brain, "test-op", "t-x", "agent-1", "hello world")
        text = (temp_brain / "wiki" / "log.md").read_text()
        assert "test-op" in text
        assert "t-x" in text
        assert "agent-1" in text
        assert "hello world" in text

    def test_creates_log_file_when_missing(self, tmp_path: Path) -> None:
        (tmp_path / "wiki").mkdir()
        assert not (tmp_path / "wiki" / "log.md").exists()
        append_log(tmp_path, "op", "t-id", "agent", "msg")
        assert (tmp_path / "wiki" / "log.md").exists()
        text = (tmp_path / "wiki" / "log.md").read_text()
        assert "op" in text

    def test_appends_multiple_entries_in_order(self, temp_brain: Path) -> None:
        append_log(temp_brain, "op1", "t-1", "agent-a", "first")
        append_log(temp_brain, "op2", "t-2", "agent-b", "second")
        text = (temp_brain / "wiki" / "log.md").read_text()
        assert "op1" in text
        assert "op2" in text
        assert text.index("op1") < text.index("op2")

    def test_default_params_work(self, temp_brain: Path) -> None:
        append_log(temp_brain, "bare-op")
        text = (temp_brain / "wiki" / "log.md").read_text()
        assert "bare-op" in text

    def test_iso_timestamp_present(self, temp_brain: Path) -> None:
        append_log(temp_brain, "ts-op", "t-ts", "agent-ts", "msg")
        text = (temp_brain / "wiki" / "log.md").read_text()
        import re
        assert re.search(r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\]", text)


# ---------------------------------------------------------------------------
# write_raw_source
# ---------------------------------------------------------------------------

class TestWriteRawSource:
    def test_writes_file_with_content(self, temp_brain: Path) -> None:
        path = write_raw_source(
            brain_value=temp_brain,
            slug="test-source",
            content="raw content here",
            title="Test Source",
        )
        assert path.exists()
        text = path.read_text()
        assert "raw content here" in text

    def test_frontmatter_title_written(self, temp_brain: Path) -> None:
        path = write_raw_source(
            brain_value=temp_brain,
            slug="titled-source",
            content="body",
            title="My Title",
        )
        text = path.read_text()
        assert "My Title" in text

    def test_file_placed_in_raw_directory(self, temp_brain: Path) -> None:
        path = write_raw_source(
            brain_value=temp_brain,
            slug="placement-test",
            content="body",
        )
        assert path.parent == temp_brain / "raw"
        assert path.suffix == ".md"

    def test_slug_becomes_filename(self, temp_brain: Path) -> None:
        path = write_raw_source(
            brain_value=temp_brain,
            slug="my-slug",
            content="body",
        )
        assert path.stem == "my-slug"

    def test_slug_normalized(self, temp_brain: Path) -> None:
        path = write_raw_source(
            brain_value=temp_brain,
            slug="Hello World",
            content="body",
        )
        assert " " not in path.stem
        assert path.stem == path.stem.lower()

    def test_raises_on_existing_without_force(self, temp_brain: Path) -> None:
        write_raw_source(brain_value=temp_brain, slug="dup-slug", content="first")
        with pytest.raises(FileExistsError):
            write_raw_source(brain_value=temp_brain, slug="dup-slug", content="second")

    def test_force_overwrites_existing(self, temp_brain: Path) -> None:
        write_raw_source(brain_value=temp_brain, slug="force-slug", content="first")
        path = write_raw_source(
            brain_value=temp_brain, slug="force-slug", content="overwritten", force=True
        )
        assert "overwritten" in path.read_text()

    def test_invalid_source_type_raises(self, temp_brain: Path) -> None:
        with pytest.raises(ValueError, match="invalid raw type"):
            write_raw_source(
                brain_value=temp_brain,
                slug="bad-type",
                content="body",
                source_type="nonexistent-type",
            )

    def test_valid_source_types_accepted(self, temp_brain: Path) -> None:
        from brain_wiki.validators import VALID_RAW_TYPES
        for i, stype in enumerate(sorted(VALID_RAW_TYPES)):
            path = write_raw_source(
                brain_value=temp_brain,
                slug=f"stype-{i}",
                content="body",
                source_type=stype,
            )
            text = path.read_text()
            assert stype in text

    def test_url_written_to_frontmatter(self, temp_brain: Path) -> None:
        path = write_raw_source(
            brain_value=temp_brain,
            slug="url-test",
            content="body",
            url="https://example.com/article",
        )
        text = path.read_text()
        assert "https://example.com/article" in text

    def test_extra_fields_included(self, temp_brain: Path) -> None:
        path = write_raw_source(
            brain_value=temp_brain,
            slug="extra-test",
            content="body",
            extra={"author": "Jane Doe", "year": "2025"},
        )
        text = path.read_text()
        assert "Jane Doe" in text

    def test_returns_path_object(self, temp_brain: Path) -> None:
        result = write_raw_source(
            brain_value=temp_brain, slug="path-obj-test", content="body"
        )
        assert isinstance(result, Path)

    def test_accepts_string_brain_path(self, temp_brain: Path) -> None:
        path = write_raw_source(
            brain_value=str(temp_brain),
            slug="str-brain",
            content="body",
        )
        assert path.exists()


# ---------------------------------------------------------------------------
# write_wiki_page
# ---------------------------------------------------------------------------

class TestWriteWikiPage:
    def test_writes_new_page(self, temp_brain: Path) -> None:
        path = write_wiki_page(
            brain_value=temp_brain,
            slug="new-page",
            content="# New\nbody text",
            title="New Page",
        )
        assert path.exists()
        text = path.read_text()
        assert "body text" in text

    def test_page_placed_in_wiki_directory(self, temp_brain: Path) -> None:
        path = write_wiki_page(
            brain_value=temp_brain, slug="wiki-dir-check", content="body"
        )
        assert path.parent == temp_brain / "wiki"
        assert path.suffix == ".md"

    def test_title_written_to_frontmatter(self, temp_brain: Path) -> None:
        path = write_wiki_page(
            brain_value=temp_brain,
            slug="titled-page",
            content="body",
            title="Explicit Title",
        )
        text = path.read_text()
        assert "Explicit Title" in text

    def test_tags_written_to_frontmatter(self, temp_brain: Path) -> None:
        path = write_wiki_page(
            brain_value=temp_brain,
            slug="tagged-page",
            content="body",
            tags=["foo", "bar"],
        )
        text = path.read_text()
        assert "foo" in text
        assert "bar" in text

    def test_invalid_page_type_raises(self, temp_brain: Path) -> None:
        with pytest.raises(ValueError, match="invalid page type"):
            write_wiki_page(
                brain_value=temp_brain,
                slug="bad-type-page",
                content="body",
                page_type="bogus",
            )

    def test_invalid_curation_raises(self, temp_brain: Path) -> None:
        with pytest.raises(ValueError, match="invalid curation"):
            write_wiki_page(
                brain_value=temp_brain,
                slug="bad-curation-page",
                content="body",
                curation="unknown-curation",
            )

    def test_protected_page_blocks_overwrite(self, temp_brain: Path) -> None:
        p = temp_brain / "wiki" / "guarded.md"
        p.write_text(
            "---\ntitle: Old\nprotected: true\ncuration: human\n---\noriginal body\n",
            encoding="utf-8",
        )
        with pytest.raises(PermissionError):
            write_wiki_page(
                brain_value=temp_brain,
                slug="guarded",
                content="new body",
                title="New",
                curation="agent",
            )
        assert "original body" in p.read_text()

    def test_protected_page_allowed_with_force(self, temp_brain: Path) -> None:
        p = temp_brain / "wiki" / "guarded2.md"
        p.write_text(
            "---\ntitle: Old\nprotected: true\ncuration: human\n---\noriginal body\n",
            encoding="utf-8",
        )
        write_wiki_page(
            brain_value=temp_brain,
            slug="guarded2",
            content="forced body",
            title="New",
            force=True,
        )
        assert "forced body" in p.read_text()

    def test_human_curation_blocks_overwrite(self, temp_brain: Path) -> None:
        p = temp_brain / "wiki" / "human-page.md"
        p.write_text(
            "---\ntitle: Old\ncuration: human\nprotected: false\n---\noriginal\n",
            encoding="utf-8",
        )
        with pytest.raises(PermissionError):
            write_wiki_page(
                brain_value=temp_brain,
                slug="human-page",
                content="replaced",
                curation="agent",
            )

    def test_update_preserves_created_date(self, temp_brain: Path) -> None:
        path = write_wiki_page(
            brain_value=temp_brain, slug="created-date", content="v1"
        )
        first_text = path.read_text()
        import re
        m = re.search(r"created: ([^\n]+)", first_text)
        original_created = m.group(1).strip() if m else None

        write_wiki_page(
            brain_value=temp_brain, slug="created-date", content="v2"
        )
        second_text = path.read_text()
        if original_created:
            assert original_created in second_text

    def test_source_summary_uses_required_policy(self, temp_brain: Path) -> None:
        path = write_wiki_page(
            brain_value=temp_brain,
            slug="src-summary",
            content="body",
            page_type="source-summary",
        )
        text = path.read_text()
        assert "required" in text

    def test_missing_source_raises(self, temp_brain: Path) -> None:
        with pytest.raises(FileNotFoundError, match="missing source"):
            write_wiki_page(
                brain_value=temp_brain,
                slug="src-missing",
                content="body",
                sources=["nonexistent-source"],
            )

    def test_valid_source_ref_accepted(self, temp_brain: Path) -> None:
        (temp_brain / "raw" / "my-source.md").write_text("# Source\n", encoding="utf-8")
        path = write_wiki_page(
            brain_value=temp_brain,
            slug="src-valid",
            content="body",
            sources=["my-source"],
        )
        assert path.exists()

    def test_update_index_calls_render(self, temp_brain: Path) -> None:
        write_wiki_page(
            brain_value=temp_brain,
            slug="indexed-page",
            content="body",
            title="Indexed",
            update_index=True,
        )
        index = temp_brain / "wiki" / "index.md"
        assert index.exists()
        assert "indexed-page" in index.read_text()

    def test_all_valid_page_types_accepted(self, temp_brain: Path) -> None:
        from brain_wiki.validators import VALID_PAGE_TYPES
        for i, ptype in enumerate(sorted(VALID_PAGE_TYPES)):
            path = write_wiki_page(
                brain_value=temp_brain,
                slug=f"ptype-{i}",
                content="body",
                page_type=ptype,
            )
            text = path.read_text()
            assert ptype in text

    def test_accepts_string_brain_path(self, temp_brain: Path) -> None:
        path = write_wiki_page(
            brain_value=str(temp_brain), slug="str-brain-wiki", content="body"
        )
        assert path.exists()

    def test_related_written_to_frontmatter(self, temp_brain: Path) -> None:
        path = write_wiki_page(
            brain_value=temp_brain,
            slug="related-page",
            content="body",
            related=["other-page"],
        )
        text = path.read_text()
        assert "other-page" in text

    def test_custom_source_policy_accepted(self, temp_brain: Path) -> None:
        path = write_wiki_page(
            brain_value=temp_brain,
            slug="policy-page",
            content="body",
            source_policy="ignored",
        )
        text = path.read_text()
        assert "ignored" in text

    def test_invalid_source_policy_raises(self, temp_brain: Path) -> None:
        with pytest.raises(ValueError, match="invalid source_policy"):
            write_wiki_page(
                brain_value=temp_brain,
                slug="bad-policy",
                content="body",
                source_policy="not-a-policy",
            )


# ---------------------------------------------------------------------------
# render_index
# ---------------------------------------------------------------------------

class TestRenderIndex:
    def test_creates_index_file(self, temp_brain: Path) -> None:
        path = render_index(temp_brain)
        assert path.exists()
        assert path.name == "index.md"

    def test_index_lists_wiki_pages(self, temp_brain: Path) -> None:
        (temp_brain / "wiki" / "page-a.md").write_text(
            "---\ntitle: A\ntype: concept\n---\n# A\n", encoding="utf-8"
        )
        (temp_brain / "wiki" / "page-b.md").write_text(
            "---\ntitle: B\ntype: concept\n---\n# B\n", encoding="utf-8"
        )
        path = render_index(temp_brain)
        text = path.read_text()
        assert "page-a" in text
        assert "page-b" in text

    def test_index_excludes_log_and_index_slugs(self, temp_brain: Path) -> None:
        (temp_brain / "wiki" / "index.md").write_text(
            "---\ntitle: Index\n---\n# Index\n", encoding="utf-8"
        )
        path = render_index(temp_brain)
        text = path.read_text()
        assert "[[log]]" not in text
        assert "[[index]]" not in text

    def test_index_groups_by_page_type(self, temp_brain: Path) -> None:
        (temp_brain / "wiki" / "ent.md").write_text(
            "---\ntitle: Ent\ntype: entity\n---\nbody\n", encoding="utf-8"
        )
        (temp_brain / "wiki" / "dec.md").write_text(
            "---\ntitle: Dec\ntype: decision\n---\nbody\n", encoding="utf-8"
        )
        path = render_index(temp_brain)
        text = path.read_text()
        assert "Entities" in text or "Decisions" in text

    def test_index_returns_path_object(self, temp_brain: Path) -> None:
        result = render_index(str(temp_brain))
        assert isinstance(result, Path)

    def test_index_accepts_string_brain(self, temp_brain: Path) -> None:
        path = render_index(str(temp_brain))
        assert path.exists()

    def test_empty_wiki_produces_valid_index(self, temp_brain: Path) -> None:
        path = render_index(temp_brain)
        text = path.read_text()
        assert "Wiki Index" in text

    def test_unknown_page_type_goes_to_other(self, temp_brain: Path) -> None:
        (temp_brain / "wiki" / "odd.md").write_text(
            "---\ntitle: Odd\ntype: weird-unknown\n---\nbody\n", encoding="utf-8"
        )
        path = render_index(temp_brain)
        text = path.read_text()
        assert "odd" in text

    def test_index_contains_wiki_index_header(self, temp_brain: Path) -> None:
        path = render_index(temp_brain)
        text = path.read_text()
        assert "# Wiki Index" in text

    def test_pages_sorted_alphabetically(self, temp_brain: Path) -> None:
        (temp_brain / "wiki" / "zzz.md").write_text(
            "---\ntitle: ZZZ\ntype: concept\n---\nbody\n", encoding="utf-8"
        )
        (temp_brain / "wiki" / "aaa.md").write_text(
            "---\ntitle: AAA\ntype: concept\n---\nbody\n", encoding="utf-8"
        )
        path = render_index(temp_brain)
        text = path.read_text()
        assert text.index("aaa") < text.index("zzz")


# ---------------------------------------------------------------------------
# lock_issues
# ---------------------------------------------------------------------------

class TestLockIssues:
    def test_no_locks_returns_empty_list(self, temp_brain: Path) -> None:
        issues = lock_issues(temp_brain)
        assert issues == []

    def test_missing_locks_dir_returns_empty_list(self, tmp_path: Path) -> None:
        issues = lock_issues(tmp_path)
        assert issues == []

    def test_stale_lock_detected(self, temp_brain: Path) -> None:
        lock_dir = temp_brain / ".locks" / "t-stale"
        lock_dir.mkdir()
        epoch = int(_dt.datetime.now(_dt.timezone.utc).timestamp()) - 9999
        (lock_dir / "owner").write_text(f"agent-x|{epoch}|1\n", encoding="utf-8")
        issues = lock_issues(temp_brain)
        assert len(issues) > 0
        messages = " ".join(i.message for i in issues)
        assert "stale" in messages.lower()

    def test_fresh_lock_not_stale(self, temp_brain: Path) -> None:
        lock_dir = temp_brain / ".locks" / "t-fresh"
        lock_dir.mkdir()
        epoch = int(_dt.datetime.now(_dt.timezone.utc).timestamp())
        (lock_dir / "owner").write_text(f"agent-y|{epoch}|600\n", encoding="utf-8")
        issues = lock_issues(temp_brain)
        assert not any("t-fresh" in i.path for i in issues)

    def test_lock_missing_owner_file_is_warned(self, temp_brain: Path) -> None:
        lock_dir = temp_brain / ".locks" / "t-no-owner"
        lock_dir.mkdir()
        issues = lock_issues(temp_brain)
        assert any("t-no-owner" in i.path for i in issues)

    def test_lock_invalid_format_is_warned(self, temp_brain: Path) -> None:
        lock_dir = temp_brain / ".locks" / "t-bad-format"
        lock_dir.mkdir()
        (lock_dir / "owner").write_text("only-one-field\n", encoding="utf-8")
        issues = lock_issues(temp_brain)
        assert any("t-bad-format" in i.path for i in issues)

    def test_lock_invalid_timestamp_is_warned(self, temp_brain: Path) -> None:
        lock_dir = temp_brain / ".locks" / "t-bad-ts"
        lock_dir.mkdir()
        (lock_dir / "owner").write_text("agent|notanint|600\n", encoding="utf-8")
        issues = lock_issues(temp_brain)
        assert any("t-bad-ts" in i.path for i in issues)

    def test_issues_are_issue_dataclass(self, temp_brain: Path) -> None:
        lock_dir = temp_brain / ".locks" / "t-typed"
        lock_dir.mkdir()
        epoch = int(_dt.datetime.now(_dt.timezone.utc).timestamp()) - 9999
        (lock_dir / "owner").write_text(f"ag|{epoch}|1\n", encoding="utf-8")
        issues = lock_issues(temp_brain)
        assert all(isinstance(i, Issue) for i in issues)

    def test_stale_lock_message_includes_agent(self, temp_brain: Path) -> None:
        lock_dir = temp_brain / ".locks" / "t-agent-info"
        lock_dir.mkdir()
        epoch = int(_dt.datetime.now(_dt.timezone.utc).timestamp()) - 9999
        (lock_dir / "owner").write_text(f"my-agent|{epoch}|1\n", encoding="utf-8")
        issues = lock_issues(temp_brain)
        messages = " ".join(i.message for i in issues)
        assert "my-agent" in messages


# ---------------------------------------------------------------------------
# obsidian_sync_report
# ---------------------------------------------------------------------------

class TestObsidianSyncReport:
    def test_all_missing_returns_not_ok(self, temp_brain: Path) -> None:
        report = obsidian_sync_report(temp_brain)
        assert report["ok"] is False
        assert len(report["missing"]) == len(OBSIDIAN_EXPECTED_VIEWS)

    def test_report_has_required_keys(self, temp_brain: Path) -> None:
        report = obsidian_sync_report(temp_brain)
        assert "ok" in report
        assert "views" in report
        assert "missing" in report
        assert "message" in report

    def test_views_list_has_all_expected(self, temp_brain: Path) -> None:
        report = obsidian_sync_report(temp_brain)
        view_names = [v["name"] for v in report["views"]]
        for expected in OBSIDIAN_EXPECTED_VIEWS:
            assert expected in view_names

    def test_all_present_returns_ok(self, temp_brain: Path) -> None:
        views_dir = temp_brain / "wiki" / "_views"
        views_dir.mkdir(parents=True)
        for name in OBSIDIAN_EXPECTED_VIEWS:
            (views_dir / name).write_text("", encoding="utf-8")
        report = obsidian_sync_report(temp_brain)
        assert report["ok"] is True
        assert report["missing"] == []

    def test_partial_views_reports_missing(self, temp_brain: Path) -> None:
        views_dir = temp_brain / "wiki" / "_views"
        views_dir.mkdir(parents=True)
        (views_dir / OBSIDIAN_EXPECTED_VIEWS[0]).write_text("", encoding="utf-8")
        report = obsidian_sync_report(temp_brain)
        assert report["ok"] is False
        assert OBSIDIAN_EXPECTED_VIEWS[0] not in report["missing"]
        assert len(report["missing"]) == len(OBSIDIAN_EXPECTED_VIEWS) - 1

    def test_each_view_entry_has_type_field(self, temp_brain: Path) -> None:
        report = obsidian_sync_report(temp_brain)
        for view in report["views"]:
            assert "type" in view
            assert isinstance(view["type"], str)

    def test_accepts_string_brain_path(self, temp_brain: Path) -> None:
        report = obsidian_sync_report(str(temp_brain))
        assert "ok" in report

    def test_message_contains_warn_when_missing(self, temp_brain: Path) -> None:
        report = obsidian_sync_report(temp_brain)
        assert "WARN" in report["message"] or "missing" in report["message"].lower()

    def test_message_contains_ok_when_all_present(self, temp_brain: Path) -> None:
        views_dir = temp_brain / "wiki" / "_views"
        views_dir.mkdir(parents=True)
        for name in OBSIDIAN_EXPECTED_VIEWS:
            (views_dir / name).write_text("", encoding="utf-8")
        report = obsidian_sync_report(temp_brain)
        assert "OK" in report["message"]

    def test_views_present_field_accurate(self, temp_brain: Path) -> None:
        views_dir = temp_brain / "wiki" / "_views"
        views_dir.mkdir(parents=True)
        # Create only one view
        (views_dir / OBSIDIAN_EXPECTED_VIEWS[0]).write_text("", encoding="utf-8")
        report = obsidian_sync_report(temp_brain)
        for view in report["views"]:
            if view["name"] == OBSIDIAN_EXPECTED_VIEWS[0]:
                assert view["present"] is True
            else:
                assert view["present"] is False


# ---------------------------------------------------------------------------
# lint_wiki (light — exercises the function, not full validation chain)
# ---------------------------------------------------------------------------

class TestLintWiki:
    def test_returns_list(self, temp_brain: Path) -> None:
        issues = lint_wiki(temp_brain)
        assert isinstance(issues, list)

    def test_empty_wiki_no_crash(self, temp_brain: Path) -> None:
        lint_wiki(temp_brain)

    def test_stale_page_detected(self, temp_brain: Path) -> None:
        (temp_brain / "wiki" / "stale.md").write_text(
            "---\ntitle: Stale\ntype: concept\nupdated: 2020-01-01\n---\nbody\n",
            encoding="utf-8",
        )
        issues = lint_wiki(temp_brain)
        stale_issues = [i for i in issues if "stale" in i.message.lower()]
        assert len(stale_issues) >= 1

    def test_accepts_string_brain_path(self, temp_brain: Path) -> None:
        issues = lint_wiki(str(temp_brain))
        assert isinstance(issues, list)

    def test_issues_are_issue_type(self, temp_brain: Path) -> None:
        issues = lint_wiki(temp_brain)
        assert all(isinstance(i, Issue) for i in issues)

    def test_missing_wikilink_target_detected(self, temp_brain: Path) -> None:
        (temp_brain / "wiki" / "linker.md").write_text(
            "---\ntitle: Linker\ntype: concept\nupdated: 2026-01-01\n---\n[[nonexistent-target]]\n",
            encoding="utf-8",
        )
        issues = lint_wiki(temp_brain)
        link_issues = [i for i in issues if "nonexistent-target" in i.message]
        assert len(link_issues) >= 1


# ---------------------------------------------------------------------------
# PAGE_TYPE_LABELS constant
# ---------------------------------------------------------------------------

class TestPageTypeLabels:
    def test_core_types_have_labels(self) -> None:
        for ptype in ("concept", "entity", "project", "decision", "source-summary"):
            assert ptype in PAGE_TYPE_LABELS

    def test_labels_are_non_empty_strings(self) -> None:
        for key, value in PAGE_TYPE_LABELS.items():
            assert isinstance(value, str)
            assert len(value) > 0
