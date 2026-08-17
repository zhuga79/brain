"""Tests for brain_wiki/validators.py (Phase 16 T7).

Target: ≥50% line coverage of runtime/lib/brain_wiki/validators.py.
"""
from __future__ import annotations

import pytest
from pathlib import Path

from brain_wiki import (
    Issue,
    is_folder_native_workspace,
    validate_paths,
    validate_raw_source,
    validate_wiki_page,
    validate_index,
    validate_task_refs,
    validate_role_uiux_routing,
    validate_uiux_skill_pack,
    validate_uiux_stale_references,
    get_uiux_skill_slugs,
    validate_all,
)
from brain_wiki.validators import (
    validate_roles,
    validate_escalation_matrix,
    _check_group_dir_exists,
    _check_required_skills_present,
    _check_skill_sections,
    _check_state_matrix,
    _check_skill_status,
    _check_skill_metadata,
    EXCLUSIVE_SYSTEM_DIRS,
    REQUIRED_DIRS,
    EXPECTED_DIRS,
    EXPECTED_FILES,
    _REQUIRED_BY_GROUP,
    _REQUIRED_SECTIONS,
    _STATE_MATRIX_ITEMS,
    _DRAFT_HANDOFF,
)


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _make_brain(tmp_path: Path, *, full: bool = True) -> Path:
    """Create a minimal valid brain layout."""
    if full:
        for d in ("raw", "wiki", "tasks"):
            (tmp_path / d).mkdir()
        (tmp_path / "tasks" / "active.md").write_text("# Active\n")
        (tmp_path / "tasks" / "done.md").write_text("# Done\n")
        (tmp_path / "wiki" / "index.md").write_text("# Index\n")
        (tmp_path / "wiki" / "log.md").write_text("# Log\n")
        (tmp_path / "MEMORY.md").write_text("# Memory\n")
    return tmp_path


def _errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "ERROR"]


def _warnings(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "WARN"]


def _msg(issues: list[Issue]) -> list[str]:
    return [i.message for i in issues]


# ---------------------------------------------------------------------------
# TestValidatePaths
# ---------------------------------------------------------------------------

class TestValidatePaths:
    def test_full_layout_no_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        issues = validate_paths(brain)
        assert _errors(issues) == []

    def test_missing_all_required_dirs_produces_errors(self, tmp_path):
        issues = validate_paths(tmp_path)
        errors = _errors(issues)
        paths = [i.path for i in errors]
        for d in REQUIRED_DIRS:
            assert any(d in p for p in paths), f"Expected error for missing required dir {d}"

    def test_missing_one_required_dir(self, tmp_path):
        (tmp_path / "wiki").mkdir()
        (tmp_path / "tasks").mkdir()
        # raw/ is missing
        issues = validate_paths(tmp_path)
        errors = _errors(issues)
        assert any("raw" in i.path for i in errors)

    def test_expected_dirs_produce_warnings(self, tmp_path):
        brain = _make_brain(tmp_path)
        issues = validate_paths(brain)
        warn_paths = [i.path for i in _warnings(issues)]
        for d in EXPECTED_DIRS:
            assert any(d in p for p in warn_paths), f"Expected warning for missing expected dir {d}"

    def test_expected_dir_present_removes_its_warning(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        issues = validate_paths(brain)
        warns = [i for i in _warnings(issues) if "roles" in i.path]
        assert warns == []

    def test_missing_memory_md_is_warning(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "MEMORY.md").unlink()
        issues = validate_paths(brain)
        warns = _warnings(issues)
        assert any("MEMORY.md" in i.path for i in warns)

    def test_missing_tasks_active_is_warning(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "tasks" / "active.md").unlink()
        issues = validate_paths(brain)
        warns = _warnings(issues)
        assert any("active.md" in i.path for i in warns)

    def test_missing_wiki_index_is_warning(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "wiki" / "index.md").unlink()
        issues = validate_paths(brain)
        warns = _warnings(issues)
        assert any("index.md" in i.path for i in warns)

    def test_missing_wiki_log_is_warning(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "wiki" / "log.md").unlink()
        issues = validate_paths(brain)
        warns = _warnings(issues)
        assert any("log.md" in i.path for i in warns)

    def test_missing_tasks_done_is_warning(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "tasks" / "done.md").unlink()
        issues = validate_paths(brain)
        warns = _warnings(issues)
        assert any("done.md" in i.path for i in warns)

    def test_error_message_contains_missing_required_directory(self, tmp_path):
        issues = validate_paths(tmp_path)
        msgs = _msg(_errors(issues))
        assert all("missing required directory" in m for m in msgs)


# ---------------------------------------------------------------------------
# TestValidateRawSource
# ---------------------------------------------------------------------------

class TestValidateRawSource:
    def _raw(self, brain: Path, name: str, content: str) -> Path:
        p = brain / "raw" / name
        p.write_text(content)
        return p

    def test_valid_raw_source(self, tmp_path):
        brain = _make_brain(tmp_path)
        content = "---\ntitle: Article\ntype: article\nfetched: 2024-01-01\n---\nBody\n"
        path = self._raw(brain, "test.md", content)
        issues = validate_raw_source(brain, path)
        assert _errors(issues) == []

    def test_missing_frontmatter(self, tmp_path):
        brain = _make_brain(tmp_path)
        path = self._raw(brain, "no-fm.md", "# No frontmatter\n")
        issues = validate_raw_source(brain, path)
        assert any("missing frontmatter" in i.message for i in _errors(issues))

    def test_missing_title_field(self, tmp_path):
        brain = _make_brain(tmp_path)
        path = self._raw(brain, "partial.md", "---\ntype: article\nfetched: 2024-01-01\n---\n")
        issues = validate_raw_source(brain, path)
        msgs = _msg(_errors(issues))
        assert any("title" in m for m in msgs)

    def test_missing_type_and_fetched(self, tmp_path):
        brain = _make_brain(tmp_path)
        path = self._raw(brain, "partial.md", "---\ntitle: Only title\n---\n")
        issues = validate_raw_source(brain, path)
        msgs = _msg(_errors(issues))
        assert any("type" in m for m in msgs)
        assert any("fetched" in m for m in msgs)

    def test_invalid_raw_type(self, tmp_path):
        brain = _make_brain(tmp_path)
        content = "---\ntitle: X\ntype: invalid-type\nfetched: 2024-01-01\n---\n"
        path = self._raw(brain, "bad-type.md", content)
        issues = validate_raw_source(brain, path)
        assert any("invalid raw type" in i.message for i in _errors(issues))

    def test_invalid_fetched_date(self, tmp_path):
        brain = _make_brain(tmp_path)
        content = "---\ntitle: X\ntype: article\nfetched: not-a-date\n---\n"
        path = self._raw(brain, "bad-date.md", content)
        issues = validate_raw_source(brain, path)
        assert any("invalid fetched date" in i.message for i in _errors(issues))

    def test_invalid_published_date_is_warning(self, tmp_path):
        brain = _make_brain(tmp_path)
        content = "---\ntitle: X\ntype: article\nfetched: 2024-01-01\npublished: bad-date\n---\n"
        path = self._raw(brain, "bad-pub.md", content)
        issues = validate_raw_source(brain, path)
        assert any("invalid published date" in i.message for i in _warnings(issues))

    def test_all_valid_types_accepted(self, tmp_path):
        brain = _make_brain(tmp_path)
        for typ in ("article", "paper", "spec", "transcript", "doc", "note", "webpage"):
            content = f"---\ntitle: X\ntype: {typ}\nfetched: 2024-01-01\n---\n"
            path = self._raw(brain, f"{typ}.md", content)
            issues = validate_raw_source(brain, path)
            type_errors = [i for i in _errors(issues) if "invalid raw type" in i.message]
            assert type_errors == [], f"type '{typ}' should be valid"

    def test_valid_published_date_no_warning(self, tmp_path):
        brain = _make_brain(tmp_path)
        content = "---\ntitle: X\ntype: article\nfetched: 2024-01-01\npublished: 2023-06-15\n---\n"
        path = self._raw(brain, "good-pub.md", content)
        issues = validate_raw_source(brain, path)
        pub_warns = [i for i in _warnings(issues) if "published" in i.message]
        assert pub_warns == []


# ---------------------------------------------------------------------------
# TestValidateWikiPage
# ---------------------------------------------------------------------------

class TestValidateWikiPage:
    def _valid_fm(self, extra: str = "") -> str:
        return (
            "---\n"
            "title: Test Page\n"
            "type: concept\n"
            "created: 2024-01-01\n"
            "updated: 2024-01-01\n"
            f"{extra}"
            "---\n"
            "Body text\n"
        )

    def test_valid_page_no_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "test-page.md"
        page.write_text(self._valid_fm())
        issues = validate_wiki_page(brain, page, {"test-page"})
        assert _errors(issues) == []

    def test_missing_frontmatter(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "no-fm.md"
        page.write_text("# No frontmatter\n")
        issues = validate_wiki_page(brain, page, {"no-fm"})
        assert any("missing frontmatter" in i.message for i in _errors(issues))

    def test_missing_title_field(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "test.md"
        page.write_text("---\ntype: concept\ncreated: 2024-01-01\nupdated: 2024-01-01\n---\n")
        issues = validate_wiki_page(brain, page, {"test"})
        assert any("title" in i.message for i in _errors(issues))

    def test_missing_type_field(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "test.md"
        page.write_text("---\ntitle: T\ncreated: 2024-01-01\nupdated: 2024-01-01\n---\n")
        issues = validate_wiki_page(brain, page, {"test"})
        assert any("type" in i.message for i in _errors(issues))

    def test_invalid_page_type(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "test.md"
        page.write_text("---\ntitle: T\ntype: invalid-type\ncreated: 2024-01-01\nupdated: 2024-01-01\n---\n")
        issues = validate_wiki_page(brain, page, {"test"})
        assert any("invalid page type" in i.message for i in _errors(issues))

    def test_valid_page_types(self, tmp_path):
        brain = _make_brain(tmp_path)
        for typ in ("concept", "entity", "project", "decision"):
            page = brain / "wiki" / f"{typ}-page.md"
            page.write_text(f"---\ntitle: T\ntype: {typ}\ncreated: 2024-01-01\nupdated: 2024-01-01\n---\n")
            issues = validate_wiki_page(brain, page, {f"{typ}-page"})
            type_errors = [i for i in _errors(issues) if "invalid page type" in i.message]
            assert type_errors == [], f"type '{typ}' should be valid"

    def test_invalid_created_date(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "test.md"
        page.write_text("---\ntitle: T\ntype: concept\ncreated: not-a-date\nupdated: 2024-01-01\n---\n")
        issues = validate_wiki_page(brain, page, {"test"})
        assert any("invalid created date" in i.message for i in _errors(issues))

    def test_invalid_updated_date(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "test.md"
        page.write_text("---\ntitle: T\ntype: concept\ncreated: 2024-01-01\nupdated: bad\n---\n")
        issues = validate_wiki_page(brain, page, {"test"})
        assert any("invalid updated date" in i.message for i in _errors(issues))

    def test_invalid_curation_value(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "test.md"
        page.write_text("---\ntitle: T\ntype: concept\ncreated: 2024-01-01\nupdated: 2024-01-01\ncuration: invalid\n---\n")
        issues = validate_wiki_page(brain, page, {"test"})
        assert any("invalid curation" in i.message for i in _errors(issues))

    def test_valid_curation_values(self, tmp_path):
        brain = _make_brain(tmp_path)
        for curation in ("human", "agent", "imported"):
            page = brain / "wiki" / "test.md"
            page.write_text(f"---\ntitle: T\ntype: concept\ncreated: 2024-01-01\nupdated: 2024-01-01\ncuration: {curation}\n---\n")
            issues = validate_wiki_page(brain, page, {"test"})
            curation_errors = [i for i in _errors(issues) if "invalid curation" in i.message]
            assert curation_errors == [], f"curation '{curation}' should be valid"

    def test_invalid_source_policy(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "test.md"
        page.write_text("---\ntitle: T\ntype: concept\ncreated: 2024-01-01\nupdated: 2024-01-01\nsource_policy: bad-policy\n---\n")
        issues = validate_wiki_page(brain, page, {"test"})
        assert any("invalid source_policy" in i.message for i in _errors(issues))

    def test_valid_source_policies(self, tmp_path):
        brain = _make_brain(tmp_path)
        for policy in ("advisory", "ignored"):
            page = brain / "wiki" / "test.md"
            page.write_text(f"---\ntitle: T\ntype: concept\ncreated: 2024-01-01\nupdated: 2024-01-01\nsource_policy: {policy}\n---\n")
            issues = validate_wiki_page(brain, page, {"test"})
            policy_errors = [i for i in _errors(issues) if "invalid source_policy" in i.message]
            assert policy_errors == [], f"source_policy '{policy}' should be valid"

    def test_broken_wikilink_detected(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "test.md"
        page.write_text(self._valid_fm() + "See [[nonexistent-page]]\n")
        issues = validate_wiki_page(brain, page, {"test"})
        assert any("nonexistent-page" in i.message for i in _errors(issues))

    def test_valid_wikilink_no_error(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "test.md"
        page.write_text(self._valid_fm() + "See [[other-page]]\n")
        issues = validate_wiki_page(brain, page, {"test", "other-page"})
        link_errors = [i for i in _errors(issues) if "broken wikilink" in i.message]
        assert link_errors == []

    def test_source_summary_requires_sources(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "test.md"
        page.write_text("---\ntitle: T\ntype: source-summary\ncreated: 2024-01-01\nupdated: 2024-01-01\n---\n")
        issues = validate_wiki_page(brain, page, {"test"})
        assert any("require sources" in i.message for i in _errors(issues))

    def test_source_policy_required_without_sources_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "test.md"
        page.write_text("---\ntitle: T\ntype: concept\ncreated: 2024-01-01\nupdated: 2024-01-01\nsource_policy: required\n---\n")
        issues = validate_wiki_page(brain, page, {"test"})
        assert any("require sources" in i.message for i in _errors(issues))

    def test_slugs_auto_resolved_when_none(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "test.md"
        page.write_text(self._valid_fm())
        # Pass slugs=None — should auto-call wiki_slugs()
        issues = validate_wiki_page(brain, page, None)
        assert isinstance(issues, list)

    def test_missing_source_file_error(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "test.md"
        page.write_text(
            "---\ntitle: T\ntype: source-summary\ncreated: 2024-01-01\nupdated: 2024-01-01\nsources: [raw/missing.md]\n---\n"
        )
        issues = validate_wiki_page(brain, page, {"test"})
        assert any("missing source" in i.message for i in _errors(issues))

    def test_valid_source_file_no_error(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "raw" / "good-source.md").write_text("---\ntitle: G\ntype: article\nfetched: 2024-01-01\n---\n")
        page = brain / "wiki" / "test.md"
        page.write_text(
            "---\ntitle: T\ntype: source-summary\ncreated: 2024-01-01\nupdated: 2024-01-01\nsources: [raw/good-source.md]\n---\n"
        )
        issues = validate_wiki_page(brain, page, {"test"})
        source_errors = [i for i in _errors(issues) if "missing source" in i.message]
        assert source_errors == []


# ---------------------------------------------------------------------------
# TestValidateIndex
# ---------------------------------------------------------------------------

class TestValidateIndex:
    def test_no_index_returns_empty(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "wiki" / "index.md").unlink()
        issues = validate_index(brain, {"some-page"})
        assert issues == []

    def test_index_valid_links_no_error(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "wiki" / "index.md").write_text("# Index\n[[my-page]]\n")
        issues = validate_index(brain, {"my-page"})
        assert _errors(issues) == []

    def test_index_broken_link_error(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "wiki" / "index.md").write_text("# Index\n[[missing-page]]\n")
        issues = validate_index(brain, {"other-page"})
        assert any("missing-page" in i.message for i in _errors(issues))

    def test_index_multiple_broken_links(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "wiki" / "index.md").write_text("[[page-a]]\n[[page-b]]\n")
        issues = validate_index(brain, set())
        assert len(_errors(issues)) == 2

    def test_index_no_wikilinks_no_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "wiki" / "index.md").write_text("# Index\nJust text, no links.\n")
        issues = validate_index(brain, set())
        assert _errors(issues) == []


# ---------------------------------------------------------------------------
# TestValidateTaskRefs
# ---------------------------------------------------------------------------

class TestValidateTaskRefs:
    def test_nonexistent_file_returns_empty(self, tmp_path):
        brain = _make_brain(tmp_path)
        nonexistent = brain / "tasks" / "nonexistent.md"
        issues = validate_task_refs(brain, nonexistent, {"some-slug"})
        assert issues == []

    def test_task_file_no_refs_no_issues(self, tmp_path):
        brain = _make_brain(tmp_path)
        path = brain / "tasks" / "active.md"
        issues = validate_task_refs(brain, path, {"some-slug"})
        assert _errors(issues) == []

    def test_broken_wikilink_in_task_ref(self, tmp_path):
        brain = _make_brain(tmp_path)
        path = brain / "tasks" / "active.md"
        path.write_text("- [ ] t-001 — Task\n      ref: [[missing-page]]\n")
        issues = validate_task_refs(brain, path, set())
        assert any("missing-page" in i.message for i in _errors(issues))

    def test_missing_raw_ref_error(self, tmp_path):
        brain = _make_brain(tmp_path)
        path = brain / "tasks" / "active.md"
        path.write_text("- [ ] t-001 — Task\n      ref: raw/missing-source.md\n")
        issues = validate_task_refs(brain, path, set())
        assert any("missing-source" in i.message for i in _errors(issues))

    def test_valid_raw_ref_no_error(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "raw" / "good-source.md").write_text("# Good\n")
        path = brain / "tasks" / "active.md"
        path.write_text("- [ ] t-001 — Task\n      ref: raw/good-source.md\n")
        issues = validate_task_refs(brain, path, set())
        raw_errors = [i for i in _errors(issues) if "missing raw reference" in i.message]
        assert raw_errors == []


# ---------------------------------------------------------------------------
# TestValidateRoleUiuxRouting
# ---------------------------------------------------------------------------

class TestValidateRoleUiuxRouting:
    def test_no_roles_dir_returns_empty(self, tmp_path):
        brain = _make_brain(tmp_path)
        issues = validate_role_uiux_routing(brain)
        assert issues == []

    def test_no_uiux_dir_returns_empty(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        issues = validate_role_uiux_routing(brain)
        assert issues == []

    def test_missing_role_file_is_warning(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        (brain / "skills" / "uiux").mkdir(parents=True)
        issues = validate_role_uiux_routing(brain)
        warns = _warnings(issues)
        assert any("designer.md" in i.path for i in warns)

    def test_designer_role_missing_patterns_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        (brain / "skills" / "uiux").mkdir(parents=True)
        (brain / "roles" / "designer.md").write_text("# Designer\nSome content\n")
        issues = validate_role_uiux_routing(brain)
        errors = _errors(issues)
        assert any("skills/uiux" in i.message for i in errors)

    def test_designer_role_with_all_patterns_no_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        (brain / "skills" / "uiux").mkdir(parents=True)
        content = "skills/uiux\n[product, designer, developer, reviewer]\n"
        (brain / "roles" / "designer.md").write_text(content)
        issues = validate_role_uiux_routing(brain)
        designer_errors = [i for i in _errors(issues) if "designer.md" in i.path]
        assert designer_errors == []

    def test_linter_role_missing_pattern_error(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        (brain / "skills" / "uiux").mkdir(parents=True)
        (brain / "roles" / "linter.md").write_text("# Linter\n")
        issues = validate_role_uiux_routing(brain)
        linter_errors = [i for i in _errors(issues) if "linter.md" in i.path]
        assert any("skill pack hygiene" in i.message for i in linter_errors)


class TestValidateRoles:
    def test_no_roles_dir_returns_empty(self, tmp_path):
        brain = _make_brain(tmp_path)
        assert validate_roles(brain) == []

    def test_valid_role_no_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        (brain / "doctrine").mkdir()
        (brain / "roles" / "developer.md").write_text(
            "---\ntype: role\ndoctrine: []\nmodel_tier: fast\nwrites: [code]\n---\n"
            "# Role: developer\n"
        )
        assert validate_roles(brain) == []

    def test_valid_role_with_existing_doctrine(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        (brain / "doctrine").mkdir()
        (brain / "doctrine" / "tax-boundaries.md").write_text("# TB\n")
        (brain / "roles" / "tax-advisor.md").write_text(
            "---\ntype: role\ndoctrine: [tax-boundaries]\nmodel_tier: powerful\nwrites: [docs]\n---\n"
            "# Role: tax-advisor\n"
        )
        assert validate_roles(brain) == []

    def test_role_without_frontmatter_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        (brain / "roles" / "broken.md").write_text("# Role: broken\n")
        errors = _errors(validate_roles(brain))
        assert any("broken.md" in i.path and "без frontmatter" in i.message for i in errors)

    def test_role_without_frontmatter_skips_field_checks(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        (brain / "roles" / "broken.md").write_text("# Role: broken\n")
        msgs = _msg(validate_roles(brain))
        assert sum("без frontmatter" in m for m in msgs) == 1

    def test_role_wrong_type_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        (brain / "roles" / "weird.md").write_text(
            "---\ntype: concept\ndoctrine: []\nmodel_tier: fast\nwrites: []\n---\n"
        )
        errors = _errors(validate_roles(brain))
        assert any("weird.md" in i.path and "ожидается 'role'" in i.message for i in errors)

    def test_role_missing_model_tier_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        (brain / "roles" / "slim.md").write_text(
            "---\ntype: role\ndoctrine: []\nwrites: [docs]\n---\n"
        )
        errors = _errors(validate_roles(brain))
        assert any("slim.md" in i.path and "model_tier" in i.message for i in errors)

    def test_role_missing_writes_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        (brain / "roles" / "slim.md").write_text(
            "---\ntype: role\ndoctrine: []\nmodel_tier: fast\n---\n"
        )
        errors = _errors(validate_roles(brain))
        assert any("slim.md" in i.path and "writes" in i.message for i in errors)

    def test_role_missing_doctrine_file_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        (brain / "doctrine").mkdir()
        (brain / "roles" / "badref.md").write_text(
            "---\ntype: role\ndoctrine: [ghost]\nmodel_tier: fast\nwrites: []\n---\n"
        )
        errors = _errors(validate_roles(brain))
        assert any("badref.md" in i.path and "нет файла doctrine/ghost.md" in i.message for i in errors)

    def test_empty_doctrine_field_accepted(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "roles").mkdir()
        (brain / "roles" / "plain.md").write_text(
            "---\ntype: role\ndoctrine: []\nmodel_tier: fast\nwrites: []\n---\n"
        )
        assert validate_roles(brain) == []


# ---------------------------------------------------------------------------
# TestValidateEscalationMatrix
# ---------------------------------------------------------------------------

_VALID_MATRIX = """\
version: 1
updated: 2026-08-11
zones:
  - id: contract-text
    name: Текст договора
    primary: [lawyer]
    escalate: [compliance]
tax_stages:
  - id: tax-stage-1
    name: Этап 1 — Учёт
    primary: [accountant]
    escalate: [tax-advisor]
"""


def _make_matrix_brain(tmp_path: Path, content: str = _VALID_MATRIX) -> Path:
    brain = _make_brain(tmp_path)
    (brain / "doctrine").mkdir()
    (brain / "doctrine" / "escalation-matrix.yaml").write_text(content, encoding="utf-8")
    (brain / "roles").mkdir()
    for role in ("lawyer", "compliance", "accountant", "tax-advisor"):
        (brain / "roles" / f"{role}.md").write_text("# role\n")
    return brain


class TestValidateEscalationMatrix:
    def test_no_doctrine_dir_returns_empty(self, tmp_path):
        brain = _make_brain(tmp_path)
        assert validate_escalation_matrix(brain) == []

    def test_missing_file_is_error(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "doctrine").mkdir()
        errors = _errors(validate_escalation_matrix(brain))
        assert any("нет файла" in i.message and "escalation-matrix.yaml" in i.path
                   for i in errors)

    def test_valid_matrix_no_errors(self, tmp_path):
        brain = _make_matrix_brain(tmp_path)
        assert validate_escalation_matrix(brain) == []

    def test_valid_matrix_empty_escalate_ok(self, tmp_path):
        content = """\
version: 1
zones:
  - id: solo-zone
    name: Зона без эскалации
    primary: [lawyer]
    escalate: []
tax_stages:
  - id: tax-stage-2
    name: Этап 2
    primary: [tax-advisor]
    escalate: []
"""
        brain = _make_matrix_brain(tmp_path, content)
        assert validate_escalation_matrix(brain) == []

    def test_missing_version_is_error(self, tmp_path):
        content = """\
zones:
  - id: contract-text
    name: Текст
    primary: [lawyer]
    escalate: []
tax_stages:
  - id: tax-stage-1
    name: Этап 1
    primary: [accountant]
    escalate: []
"""
        brain = _make_matrix_brain(tmp_path, content)
        errors = _errors(validate_escalation_matrix(brain))
        assert any("version" in i.message for i in errors)

    def test_missing_primary_role_is_error(self, tmp_path):
        content = _VALID_MATRIX.replace("primary: [lawyer]", "primary: [ghost-role]")
        brain = _make_matrix_brain(tmp_path, content)
        errors = _errors(validate_escalation_matrix(brain))
        assert any("primary-роль 'ghost-role'" in i.message for i in errors)

    def test_missing_escalate_role_is_error(self, tmp_path):
        content = _VALID_MATRIX.replace("escalate: [compliance]", "escalate: [ghost-role]")
        brain = _make_matrix_brain(tmp_path, content)
        errors = _errors(validate_escalation_matrix(brain))
        assert any("escalate-роль 'ghost-role'" in i.message for i in errors)

    def test_primary_must_be_nonempty_list(self, tmp_path):
        content = _VALID_MATRIX.replace("primary: [lawyer]", "primary: []")
        brain = _make_matrix_brain(tmp_path, content)
        errors = _errors(validate_escalation_matrix(brain))
        assert any("primary должен быть непустым списком" in i.message for i in errors)

    def test_duplicate_ids_are_errors(self, tmp_path):
        content = _VALID_MATRIX.replace(
            "zones:\n  - id: contract-text",
            "zones:\n  - id: contract-text\n  - id: contract-text",
        )
        brain = _make_matrix_brain(tmp_path, content)
        errors = _errors(validate_escalation_matrix(brain))
        assert any("дубликат id 'contract-text'" in i.message for i in errors)

    def test_missing_name_is_error(self, tmp_path):
        content = _VALID_MATRIX.replace("    name: Текст договора", "    name: ''")
        brain = _make_matrix_brain(tmp_path, content)
        errors = _errors(validate_escalation_matrix(brain))
        assert any("отсутствует name" in i.message for i in errors)

    def test_unparsable_matrix_is_error(self, tmp_path):
        brain = _make_matrix_brain(tmp_path, "zones:\n    name: no item\n")
        errors = _errors(validate_escalation_matrix(brain))
        assert any("вне элемента списка" in i.message for i in errors)

    def test_missing_section_is_error(self, tmp_path):
        content = """\
version: 1
zones:
  - id: contract-text
    name: Текст
    primary: [lawyer]
    escalate: []
"""
        brain = _make_matrix_brain(tmp_path, content)
        errors = _errors(validate_escalation_matrix(brain))
        assert any("tax_stages" in i.message for i in errors)

    def test_missing_role_files_empty_roles_dir_reports_all(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "doctrine").mkdir()
        (brain / "doctrine" / "escalation-matrix.yaml").write_text(_VALID_MATRIX)
        (brain / "roles").mkdir()
        errors = _errors(validate_escalation_matrix(brain))
        assert any("primary-роль 'lawyer'" in i.message for i in errors)
        assert any("escalate-роль 'compliance'" in i.message for i in errors)


# ---------------------------------------------------------------------------
# TestPrivateHelpers
# ---------------------------------------------------------------------------

class TestCheckGroupDirExists:
    def test_existing_dir_returns_empty(self, tmp_path):
        uiux = tmp_path / "skills" / "uiux"
        (uiux / "core").mkdir(parents=True)
        assert _check_group_dir_exists(uiux, "core") == []

    def test_missing_dir_returns_error(self, tmp_path):
        uiux = tmp_path / "skills" / "uiux"
        uiux.mkdir(parents=True)
        issues = _check_group_dir_exists(uiux, "core")
        assert len(issues) == 1
        assert issues[0].severity == "ERROR"
        assert "core" in issues[0].path


class TestCheckRequiredSkillsPresent:
    def test_all_present_returns_empty(self, tmp_path):
        group_dir = tmp_path / "core"
        group_dir.mkdir()
        for slug in _REQUIRED_BY_GROUP["core"]:
            (group_dir / f"{slug}.md").write_text("# Skill\n")
        issues = _check_required_skills_present(group_dir, "core")
        assert issues == []

    def test_missing_skill_returns_error(self, tmp_path):
        group_dir = tmp_path / "core"
        group_dir.mkdir()
        (group_dir / "ux-task-framing.md").write_text("# Skill\n")
        issues = _check_required_skills_present(group_dir, "core")
        missing_slugs = _REQUIRED_BY_GROUP["core"] - {"ux-task-framing"}
        assert len(issues) == len(missing_slugs)

    def test_all_missing_returns_all_errors(self, tmp_path):
        group_dir = tmp_path / "brain"
        group_dir.mkdir()
        issues = _check_required_skills_present(group_dir, "brain")
        assert len(issues) == len(_REQUIRED_BY_GROUP["brain"])


class TestCheckSkillSections:
    def test_all_sections_present(self):
        content = "\n".join(_REQUIRED_SECTIONS) + "\nContent\n"
        assert _check_skill_sections("rel.md", content) == []

    def test_missing_section_is_error(self):
        # Only Trigger section present
        issues = _check_skill_sections("rel.md", "## Trigger\nsome content")
        assert len(issues) == len(_REQUIRED_SECTIONS) - 1

    def test_all_sections_missing(self):
        issues = _check_skill_sections("rel.md", "No sections here")
        assert len(issues) == len(_REQUIRED_SECTIONS)

    def test_error_message_contains_section_name(self):
        issues = _check_skill_sections("rel.md", "No sections here")
        for issue in issues:
            assert "missing required section" in issue.message


class TestCheckStateMatrix:
    def test_core_group_checks_matrix(self):
        issues = _check_state_matrix("rel.md", "no matrix", "core")
        assert len(issues) == len(_STATE_MATRIX_ITEMS)

    def test_core_group_all_items_present(self):
        content = "\n".join(_STATE_MATRIX_ITEMS)
        issues = _check_state_matrix("rel.md", content, "core")
        assert issues == []

    def test_brain_group_checks_matrix(self):
        issues = _check_state_matrix("rel.md", "no matrix", "brain")
        assert len(issues) == len(_STATE_MATRIX_ITEMS)

    def test_brain_group_all_items_present(self):
        content = "\n".join(_STATE_MATRIX_ITEMS)
        issues = _check_state_matrix("rel.md", content, "brain")
        assert issues == []

    def test_handoff_group_skips_matrix(self):
        issues = _check_state_matrix("rel.md", "no matrix", "handoff")
        assert issues == []

    def test_partial_matrix_returns_partial_errors(self):
        # Only first item present
        content = _STATE_MATRIX_ITEMS[0]
        issues = _check_state_matrix("rel.md", content, "core")
        assert len(issues) == len(_STATE_MATRIX_ITEMS) - 1


class TestCheckSkillStatus:
    def test_core_skill_must_be_active(self):
        slug = next(iter(_REQUIRED_BY_GROUP["core"]))
        issues = _check_skill_status("rel.md", slug, "core", "draft")
        assert len(issues) == 1
        assert "must be active" in issues[0].message

    def test_core_skill_active_is_ok(self):
        slug = next(iter(_REQUIRED_BY_GROUP["core"]))
        issues = _check_skill_status("rel.md", slug, "core", "active")
        assert issues == []

    def test_brain_skill_must_be_active(self):
        slug = next(iter(_REQUIRED_BY_GROUP["brain"]))
        issues = _check_skill_status("rel.md", slug, "brain", "draft")
        assert any("must be active" in i.message for i in issues)

    def test_brain_skill_active_is_ok(self):
        slug = next(iter(_REQUIRED_BY_GROUP["brain"]))
        issues = _check_skill_status("rel.md", slug, "brain", "active")
        assert issues == []

    def test_handoff_draft_skill_must_be_draft(self):
        slug = next(iter(_DRAFT_HANDOFF))
        issues = _check_skill_status("rel.md", slug, "handoff", "active")
        assert any("must be draft" in i.message for i in issues)

    def test_handoff_draft_skill_status_draft_is_ok(self):
        slug = next(iter(_DRAFT_HANDOFF))
        issues = _check_skill_status("rel.md", slug, "handoff", "draft")
        assert issues == []

    def test_handoff_active_skill_must_be_active(self):
        active_slugs = _REQUIRED_BY_GROUP["handoff"] - _DRAFT_HANDOFF
        slug = next(iter(active_slugs))
        issues = _check_skill_status("rel.md", slug, "handoff", "draft")
        assert any("must be active" in i.message for i in issues)

    def test_handoff_active_skill_is_ok(self):
        active_slugs = _REQUIRED_BY_GROUP["handoff"] - _DRAFT_HANDOFF
        slug = next(iter(active_slugs))
        issues = _check_skill_status("rel.md", slug, "handoff", "active")
        assert issues == []

    def test_unknown_slug_no_status_check(self):
        issues = _check_skill_status("rel.md", "custom-skill", "brain", "draft")
        assert issues == []


# ---------------------------------------------------------------------------
# TestValidateUiuxSkillPack
# ---------------------------------------------------------------------------

class TestValidateUiuxSkillPack:
    def test_no_uiux_dir_returns_empty(self, tmp_path):
        brain = _make_brain(tmp_path)
        issues = validate_uiux_skill_pack(brain)
        assert issues == []

    def test_missing_group_dirs_produce_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "skills" / "uiux").mkdir(parents=True)
        issues = validate_uiux_skill_pack(brain)
        errors = _errors(issues)
        assert any("core" in i.path for i in errors)
        assert any("brain" in i.path for i in errors)
        assert any("handoff" in i.path for i in errors)

    def test_missing_required_skills_in_group(self, tmp_path):
        brain = _make_brain(tmp_path)
        uiux = brain / "skills" / "uiux"
        for g in ("core", "brain", "handoff"):
            (uiux / g).mkdir(parents=True)
        issues = validate_uiux_skill_pack(brain)
        errors = _errors(issues)
        assert len(errors) >= len(_REQUIRED_BY_GROUP["core"])

    def test_skill_missing_frontmatter_error(self, tmp_path):
        brain = _make_brain(tmp_path)
        uiux = brain / "skills" / "uiux"
        for g in ("core", "brain", "handoff"):
            (uiux / g).mkdir(parents=True)
        (uiux / "core" / "ux-task-framing.md").write_text("# No frontmatter\n")
        issues = validate_uiux_skill_pack(brain)
        assert any("missing frontmatter" in i.message for i in _errors(issues))

    def test_only_core_dir_missing_brain_and_handoff_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        uiux = brain / "skills" / "uiux"
        (uiux / "core").mkdir(parents=True)
        issues = validate_uiux_skill_pack(brain)
        paths = [i.path for i in _errors(issues)]
        assert any("brain" in p for p in paths)
        assert any("handoff" in p for p in paths)


# ---------------------------------------------------------------------------
# TestGetUiuxSkillSlugs
# ---------------------------------------------------------------------------

class TestGetUiuxSkillSlugs:
    def test_no_uiux_dir_returns_empty_set(self, tmp_path):
        brain = _make_brain(tmp_path)
        slugs = get_uiux_skill_slugs(brain)
        assert slugs == set()

    def test_collects_slugs_from_all_groups(self, tmp_path):
        brain = _make_brain(tmp_path)
        uiux = brain / "skills" / "uiux"
        for group in ("core", "brain", "handoff"):
            (uiux / group).mkdir(parents=True)
            (uiux / group / f"{group}-skill-one.md").write_text("# Skill\n")
        slugs = get_uiux_skill_slugs(brain)
        assert "core-skill-one" in slugs
        assert "brain-skill-one" in slugs
        assert "handoff-skill-one" in slugs

    def test_missing_group_dir_gracefully_skipped(self, tmp_path):
        brain = _make_brain(tmp_path)
        uiux = brain / "skills" / "uiux"
        (uiux / "core").mkdir(parents=True)
        (uiux / "core" / "ux-task-framing.md").write_text("# Skill\n")
        # brain and handoff dirs missing — should not error
        slugs = get_uiux_skill_slugs(brain)
        assert "ux-task-framing" in slugs

    def test_multiple_skills_per_group(self, tmp_path):
        brain = _make_brain(tmp_path)
        uiux = brain / "skills" / "uiux"
        (uiux / "core").mkdir(parents=True)
        for slug in ("ux-task-framing", "ui-critique", "workflow-design"):
            (uiux / "core" / f"{slug}.md").write_text("# Skill\n")
        slugs = get_uiux_skill_slugs(brain)
        assert {"ux-task-framing", "ui-critique", "workflow-design"}.issubset(slugs)


# ---------------------------------------------------------------------------
# TestValidateUiuxStaleReferences
# ---------------------------------------------------------------------------

class TestValidateUiuxStaleReferences:
    def test_no_skills_returns_empty(self, tmp_path):
        brain = _make_brain(tmp_path)
        issues = validate_uiux_stale_references(brain)
        assert issues == []

    def test_valid_skill_path_ref_in_roles(self, tmp_path):
        brain = _make_brain(tmp_path)
        uiux = brain / "skills" / "uiux"
        (uiux / "core").mkdir(parents=True)
        (uiux / "core" / "ux-task-framing.md").write_text("# Skill\n")
        (brain / "roles").mkdir()
        (brain / "roles" / "designer.md").write_text(
            "Use skills/uiux/core/ux-task-framing here\n"
        )
        issues = validate_uiux_stale_references(brain)
        ref_errors = [i for i in _errors(issues) if "broken skill reference" in i.message]
        assert ref_errors == []

    def test_broken_skill_path_ref_in_roles(self, tmp_path):
        brain = _make_brain(tmp_path)
        uiux = brain / "skills" / "uiux"
        (uiux / "core").mkdir(parents=True)
        (uiux / "core" / "ux-task-framing.md").write_text("# Skill\n")
        (brain / "roles").mkdir()
        (brain / "roles" / "designer.md").write_text(
            "See skills/uiux/core/nonexistent-skill\n"
        )
        issues = validate_uiux_stale_references(brain)
        assert any("nonexistent-skill" in i.message for i in _errors(issues))

    def test_stale_backtick_ref_in_roles(self, tmp_path):
        brain = _make_brain(tmp_path)
        uiux = brain / "skills" / "uiux"
        (uiux / "core").mkdir(parents=True)
        (uiux / "core" / "ux-task-framing.md").write_text("# Skill\n")
        (brain / "roles").mkdir()
        (brain / "roles" / "designer.md").write_text(
            "Use `ux-missing-skill` here\n"
        )
        issues = validate_uiux_stale_references(brain)
        assert any("ux-missing-skill" in i.message for i in _errors(issues))

    def test_valid_backtick_ref_no_error(self, tmp_path):
        brain = _make_brain(tmp_path)
        uiux = brain / "skills" / "uiux"
        (uiux / "core").mkdir(parents=True)
        (uiux / "core" / "ux-task-framing.md").write_text("# Skill\n")
        (brain / "roles").mkdir()
        (brain / "roles" / "designer.md").write_text(
            "Use `ux-task-framing` here\n"
        )
        issues = validate_uiux_stale_references(brain)
        ref_errors = [i for i in _errors(issues) if "ux-task-framing" in i.message]
        assert ref_errors == []

    def test_group_level_ref_skipped(self, tmp_path):
        brain = _make_brain(tmp_path)
        uiux = brain / "skills" / "uiux"
        (uiux / "core").mkdir(parents=True)
        (uiux / "core" / "ux-task-framing.md").write_text("# Skill\n")
        (brain / "roles").mkdir()
        # Reference to group dir itself (skills/uiux/core) — should be skipped
        (brain / "roles" / "designer.md").write_text(
            "See skills/uiux/core for all core skills\n"
        )
        issues = validate_uiux_stale_references(brain)
        # "core" itself is skipped — no error for it
        group_errors = [
            i for i in _errors(issues)
            if i.message == "broken skill reference: skills/uiux/core"
        ]
        assert group_errors == []

    def test_invalid_path_format_error(self, tmp_path):
        brain = _make_brain(tmp_path)
        uiux = brain / "skills" / "uiux"
        (uiux / "core").mkdir(parents=True)
        (uiux / "core" / "ux-task-framing.md").write_text("# Skill\n")
        (brain / "roles").mkdir()
        # Three-part path: skills/uiux/core/extra/something
        (brain / "roles" / "designer.md").write_text(
            "See skills/uiux/core/extra/something\n"
        )
        issues = validate_uiux_stale_references(brain)
        assert any("invalid skill path format" in i.message for i in _errors(issues))

    def test_spec_dir_is_searched(self, tmp_path):
        brain = _make_brain(tmp_path)
        uiux = brain / "skills" / "uiux"
        (uiux / "core").mkdir(parents=True)
        (uiux / "core" / "ux-task-framing.md").write_text("# Skill\n")
        (brain / "spec").mkdir()
        (brain / "spec" / "design-spec.md").write_text(
            "Ref skills/uiux/core/nonexistent\n"
        )
        issues = validate_uiux_stale_references(brain)
        assert any("nonexistent" in i.message for i in _errors(issues))

    def test_handoff_dir_is_searched(self, tmp_path):
        brain = _make_brain(tmp_path)
        uiux = brain / "skills" / "uiux"
        (uiux / "core").mkdir(parents=True)
        (uiux / "core" / "ux-task-framing.md").write_text("# Skill\n")
        (brain / "handoff").mkdir()
        (brain / "handoff" / "notes.md").write_text(
            "Ref skills/uiux/core/nonexistent\n"
        )
        issues = validate_uiux_stale_references(brain)
        assert any("nonexistent" in i.message for i in _errors(issues))


# ---------------------------------------------------------------------------
# TestValidateAll
# ---------------------------------------------------------------------------

class TestValidateAll:
    def test_clean_minimal_brain_no_errors(self, tmp_path):
        brain = _make_brain(tmp_path)
        issues = validate_all(str(brain))
        errors = _errors(issues)
        assert errors == []

    def test_missing_required_dirs_returns_early(self, tmp_path):
        # Empty brain — required dirs missing → returns immediately with errors
        issues = validate_all(str(tmp_path))
        errors = _errors(issues)
        assert len(errors) >= len(REQUIRED_DIRS)

    def test_accepts_path_object(self, tmp_path):
        brain = _make_brain(tmp_path)
        issues = validate_all(brain)
        assert isinstance(issues, list)

    def test_accepts_none_uses_env_brain(self, tmp_path, monkeypatch):
        brain = _make_brain(tmp_path)
        monkeypatch.setenv("BRAIN", str(brain))
        issues = validate_all(None)
        assert isinstance(issues, list)

    def test_wiki_page_errors_included(self, tmp_path):
        brain = _make_brain(tmp_path)
        page = brain / "wiki" / "bad-page.md"
        page.write_text("---\ntitle: Bad\n---\nNo type/created/updated\n")
        issues = validate_all(str(brain))
        assert any("bad-page" in i.path for i in issues)

    def test_raw_source_errors_included(self, tmp_path):
        brain = _make_brain(tmp_path)
        raw = brain / "raw" / "bad-source.md"
        raw.write_text("# No frontmatter\n")
        issues = validate_all(str(brain))
        assert any("bad-source" in i.path for i in issues)

    def test_index_errors_included(self, tmp_path):
        brain = _make_brain(tmp_path)
        (brain / "wiki" / "index.md").write_text("[[missing-page]]\n")
        issues = validate_all(str(brain))
        assert any("missing-page" in i.message for i in issues)

    def test_returns_list_type(self, tmp_path):
        brain = _make_brain(tmp_path)
        issues = validate_all(str(brain))
        assert isinstance(issues, list)
        for issue in issues:
            assert isinstance(issue, Issue)

    def test_early_return_skips_wiki_validation(self, tmp_path):
        # When required dirs are missing, validate_all returns early
        # so wiki content-validation errors (broken wikilinks etc.) should NOT be present
        issues = validate_all(str(tmp_path))
        # Only path-level issues (errors/warnings about dirs/files) should be present
        content_errors = [
            i for i in issues
            if i.severity == "ERROR" and "wiki/" in i.path and "missing required" not in i.message
        ]
        assert content_errors == []


# ---------------------------------------------------------------------------
# TestIsFolderNativeWorkspace / TestValidateAllFolderNativeWorkspace
#
# t-2026-08-17-folder-native-workspace-contour: folder-native рабочая папка —
# сознательно ограниченный контур (docs/decisions/decision-runtime-core-
# boundaries.md, раздел 9). brain-validate не применяет к ней схему
# системного корня — ни REQUIRED_DIRS, ни EXCLUSIVE_SYSTEM_DIRS.
# ---------------------------------------------------------------------------

def _make_workspace(tmp_path: Path) -> Path:
    """A minimal folder-native workspace: BRAIN.md + TASKS.md + LOG.md,
    deliberately without raw/, wiki/, tasks/active.md."""
    (tmp_path / "BRAIN.md").write_text("# Case Folder\n\n> A client matter folder.\n")
    (tmp_path / "TASKS.md").write_text(
        "# Local Tasks\n\n- [ ] [P1] local-001 - Do the thing\n      role: developer\n"
    )
    (tmp_path / "LOG.md").write_text("# Local Log\n")
    return tmp_path


class TestIsFolderNativeWorkspace:
    def test_true_when_brain_md_present(self, tmp_path):
        _make_workspace(tmp_path)
        assert is_folder_native_workspace(tmp_path) is True

    def test_false_when_brain_md_absent(self, tmp_path):
        brain = _make_brain(tmp_path)
        assert is_folder_native_workspace(brain) is False

    def test_false_when_brain_md_is_a_directory(self, tmp_path):
        (tmp_path / "BRAIN.md").mkdir()
        assert is_folder_native_workspace(tmp_path) is False


class TestValidateAllFolderNativeWorkspace:
    def test_no_errors_or_warnings(self, tmp_path):
        workspace = _make_workspace(tmp_path)
        issues = validate_all(str(workspace))
        assert _errors(issues) == []
        assert _warnings(issues) == []

    def test_single_info_issue_points_at_brain_workspace(self, tmp_path):
        workspace = _make_workspace(tmp_path)
        issues = validate_all(str(workspace))
        assert len(issues) == 1
        assert issues[0].severity == "INFO"
        assert "brain-workspace" in issues[0].message

    def test_reserved_system_dir_names_are_not_flagged(self, tmp_path):
        # These names are legal in a case folder for its own purposes; the
        # system-root restriction (EXCLUSIVE_SYSTEM_DIRS) must not reach it.
        workspace = _make_workspace(tmp_path)
        for name in EXCLUSIVE_SYSTEM_DIRS:
            (workspace / name).mkdir()
        issues = validate_all(str(workspace))
        assert _errors(issues) == []
        assert not any(name in i.path for name in EXCLUSIVE_SYSTEM_DIRS for i in issues)

    def test_missing_root_schema_dirs_are_not_flagged(self, tmp_path):
        # raw/, wiki/, tasks/ are absent by contract in a folder-native
        # workspace; REQUIRED_DIRS must not apply here.
        workspace = _make_workspace(tmp_path)
        issues = validate_all(str(workspace))
        assert not any("missing required directory" in i.message for i in issues)

    def test_workspace_queue_is_readable_by_brain_workspace_regardless(self, tmp_path):
        # The workspace's own queue keeps working; brain-validate opting out
        # does not touch brain_workspace's own parsing.
        from brain_workspace import parse_local_tasks

        workspace = _make_workspace(tmp_path)
        tasks = parse_local_tasks(workspace / "TASKS.md")
        assert [t.task_id for t in tasks] == ["local-001"]
