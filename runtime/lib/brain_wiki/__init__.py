"""brain_wiki — Brain wiki/raw helpers package.

This package is intentionally dependency-free. Re-exports all public
symbols from the submodules so that existing code using:
    import brain_wiki
    from brain_wiki import parse_frontmatter
continues to work without modification.
"""

from __future__ import annotations

# --- frontmatter -----------------------------------------------------------
from .frontmatter import (
    _format_scalar,
    _parse_scalar,
    _strip_quotes,
    as_bool,
    as_list,
    format_frontmatter,
    parse_frontmatter,
    validate_date,
)

# --- pages / utils ---------------------------------------------------------
from .pages import (
    INDEX_EXCLUDED,
    Issue,
    all_page_slugs,
    brain_path,
    existing_page_is_protected,
    extract_task_refs,
    extract_wikilinks,
    iter_system_doc_pages,
    iter_wiki_pages,
    normalize_slug,
    raw_ref_to_path,
    read_text,
    source_refs,
    today,
    utc_ts,
    wiki_slugs,
    write_text,
)

# --- validators ------------------------------------------------------------
from .validators import (
    VALID_CURATION,
    VALID_PAGE_TYPES,
    VALID_RAW_TYPES,
    VALID_SOURCE_POLICIES,
    get_uiux_skill_slugs,
    is_folder_native_workspace,
    validate_all,
    validate_escalation_matrix,
    validate_index,
    validate_installer_shadows,
    validate_paths,
    validate_raw_source,
    validate_role_uiux_routing,
    validate_routing,
    validate_staged_write_path,
    validate_system_paths_not_restored,
    validate_task_refs,
    validate_uiux_skill_pack,
    validate_uiux_stale_references,
    validate_wiki_page,
)

# --- writers ---------------------------------------------------------------
from .writers import (
    OBSIDIAN_EXPECTED_VIEWS,
    PAGE_TYPE_LABELS,
    append_log,
    lint_wiki,
    lock_issues,
    obsidian_sync_report,
    render_index,
    write_raw_source,
    write_wiki_page,
)

__all__ = [
    # frontmatter
    "_format_scalar",
    "_parse_scalar",
    "_strip_quotes",
    "as_bool",
    "as_list",
    "format_frontmatter",
    "parse_frontmatter",
    "validate_date",
    # pages
    "INDEX_EXCLUDED",
    "Issue",
    "all_page_slugs",
    "brain_path",
    "existing_page_is_protected",
    "extract_task_refs",
    "extract_wikilinks",
    "iter_system_doc_pages",
    "iter_wiki_pages",
    "normalize_slug",
    "raw_ref_to_path",
    "read_text",
    "source_refs",
    "today",
    "utc_ts",
    "wiki_slugs",
    "write_text",
    # validators
    "VALID_CURATION",
    "VALID_PAGE_TYPES",
    "VALID_RAW_TYPES",
    "VALID_SOURCE_POLICIES",
    "get_uiux_skill_slugs",
    "is_folder_native_workspace",
    "validate_all",
    "validate_escalation_matrix",
    "validate_index",
    "validate_installer_shadows",
    "validate_paths",
    "validate_raw_source",
    "validate_role_uiux_routing",
    "validate_routing",
    "validate_staged_write_path",
    "validate_system_paths_not_restored",
    "validate_task_refs",
    "validate_uiux_skill_pack",
    "validate_uiux_stale_references",
    "validate_wiki_page",
    # writers
    "OBSIDIAN_EXPECTED_VIEWS",
    "PAGE_TYPE_LABELS",
    "append_log",
    "lint_wiki",
    "lock_issues",
    "obsidian_sync_report",
    "render_index",
    "write_raw_source",
    "write_wiki_page",
]
