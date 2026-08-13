"""Page utilities, raw helpers and filesystem primitives for Brain wiki.

Provides core helpers that are used by all other brain_wiki submodules:
utc_ts, today, normalize_slug, brain_path, read_text, write_text,
extract_wikilinks, iter_wiki_pages, wiki_slugs, raw_ref_to_path,
source_refs, extract_task_refs, existing_page_is_protected, and the
Issue dataclass.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .frontmatter import as_bool, as_list

INDEX_EXCLUDED = {"index", "log"}


@dataclass(frozen=True)
class Issue:
    severity: str
    path: str
    message: str

    def format(self) -> str:
        return f"{self.severity}: {self.path}: {self.message}"


def utc_ts() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    return _dt.date.today().isoformat()


def normalize_slug(text: str) -> str:
    """Normalize text to an Obsidian-friendly filename slug."""
    slug = text.strip().lower()
    slug = re.sub(r"[\\/]+", "-", slug)
    slug = re.sub(r"[^\w.-]+", "-", slug, flags=re.UNICODE)
    slug = re.sub(r"-+", "-", slug).strip("-._")
    return slug or _dt.datetime.now().strftime("source-%Y%m%d-%H%M%S")


def brain_path(value: str | None = None) -> Path:
    return Path(value or os.environ.get("BRAIN_PATH", str(Path.home() / "brain"))).expanduser()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, content: str) -> None:
    """Записать файл атомарно.

    Через эту функцию пишется индекс, который параллельно читает brain-search.
    Прямой write_text оставляет окно, в котором файл уже усечён, но ещё не
    дописан — читатель в этот момент получает пустой или обрезанный JSON.
    """
    from brain_core import atomic

    atomic.write_text(path, content)


def extract_wikilinks(content: str) -> list[str]:
    links = []
    for match in re.finditer(r"\[\[([^\]]+)\]\]", content):
        target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
        if target.startswith("wiki/"):
            target = target[5:]
        if target.endswith(".md"):
            target = target[:-3]
        if target:
            links.append(target)
    return links


def iter_wiki_pages(brain: Path) -> Iterable[Path]:
    wiki = brain / "wiki"
    if not wiki.exists():
        return []
    return sorted(path for path in wiki.glob("*.md") if path.stem not in INDEX_EXCLUDED)


def wiki_slugs(brain: Path) -> set[str]:
    wiki = brain / "wiki"
    if not wiki.exists():
        return set()
    return {path.stem for path in wiki.glob("*.md")}


def raw_ref_to_path(brain: Path, ref: str) -> Path:
    ref = ref.strip()
    if ref.startswith("raw/"):
        rel = ref
    elif ref.endswith(".md"):
        rel = f"raw/{Path(ref).name}"
    else:
        rel = f"raw/{ref}.md"
    return brain / rel


def source_refs(frontmatter: dict[str, Any]) -> list[str]:
    refs = as_list(frontmatter.get("sources"))
    if "source" in frontmatter:
        refs.extend(as_list(frontmatter.get("source")))
    return refs


def extract_task_refs(content: str) -> list[tuple[str, str]]:
    refs = []
    for match in re.finditer(r"^\s*ref:\s*(.+)$", content, re.M):
        refs.append((match.group(1).strip(), f"line {content[:match.start()].count(chr(10)) + 1}"))
    return refs


def existing_page_is_protected(frontmatter: dict[str, Any]) -> bool:
    return as_bool(frontmatter.get("protected")) or frontmatter.get("curation") == "human"
