"""brain_index must not crash the whole index build when a single file's
frontmatter is outside the supported YAML subset — the record is flagged with
an `error` marker and the tree walk continues (t-2026-08-18-...).
"""
from pathlib import Path

import brain_index


def _make_brain(tmp_path: Path) -> Path:
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
    (tmp_path / "tasks").mkdir()
    (tmp_path / "wiki" / "log.md").write_text("# Log\n\n", encoding="utf-8")
    (tmp_path / "wiki" / "good.md").write_text(
        "---\ntitle: Good Page\ntype: concept\n"
        "sources:\n  - raw/a.md\n---\n# Good body\n",
        encoding="utf-8",
    )
    (tmp_path / "raw" / "a.md").write_text(
        "---\ntitle: Source A\n---\nraw body", encoding="utf-8"
    )
    return tmp_path


def test_page_record_flags_bad_frontmatter(tmp_path):
    brain = _make_brain(tmp_path)
    bad = brain / "wiki" / "bad.md"
    bad.write_text("---\nnote: |\n  multi\n  line\n---\nBody\n", encoding="utf-8")
    rec = brain_index.page_record(brain, bad, {"good", "bad"})
    assert "error" in rec
    assert "frontmatter" in rec["error"].lower()
    assert rec["slug"] == "bad"
    assert rec["title"] == "bad"


def test_rebuild_index_survives_bad_wiki_frontmatter(tmp_path, capsys):
    brain = _make_brain(tmp_path)
    (brain / "wiki" / "bad.md").write_text(
        "---\nnote: |\n  x\n  y\n---\nBad body\n", encoding="utf-8"
    )
    manifest = brain_index.rebuild_index(brain)
    assert manifest["page_count"] == 2

    pages = brain_index.load_json(brain / ".brain" / "index" / "pages.json", {})["pages"]
    by_slug = {p["slug"]: p for p in pages}
    assert by_slug["good"]["title"] == "Good Page"
    assert "error" in by_slug["bad"]
    assert "frontmatter" in by_slug["bad"]["error"].lower()

    err = capsys.readouterr().err
    assert "bad.md" in err


def test_rebuild_index_survives_bad_raw_frontmatter(tmp_path, capsys):
    brain = _make_brain(tmp_path)
    (brain / "raw" / "bad.md").write_text(
        "---\ntitle: |\n  x\n---\nbody\n", encoding="utf-8"
    )
    manifest = brain_index.rebuild_index(brain)
    assert manifest["raw_count"] == 2

    sources = brain_index.load_json(brain / ".brain" / "index" / "sources.json", {})
    records = sources["raw"]
    by_slug = {r["slug"]: r for r in records}
    assert by_slug["a"]["title"] == "Source A"
    assert "error" in by_slug["bad"]

    err = capsys.readouterr().err
    assert "raw/bad.md" in err


def test_bad_frontmatter_page_still_in_search_corpus(tmp_path):
    brain = _make_brain(tmp_path)
    (brain / "wiki" / "bad.md").write_text(
        "---\nnote: |\n  x\n---\nUniqueCorpusToken for bad page\n", encoding="utf-8"
    )
    brain_index.rebuild_index(brain)
    results = brain_index.search_brain(brain, "UniqueCorpusToken")
    assert any(res["id"] == "bad" for res in results)