"""brain_learning — shared library for Learning Loop data access."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_VALID_STATUSES = {"pending", "approved", "active", "rejected", "deprecated"}
_VALID_SEVERITIES = {"low", "medium", "high"}
_VALID_SOURCES = {
    "human-edit", "human-review", "test-failure", "smoke-failure",
    "lint-failure", "validate-failure", "runtime-error", "ci-failure",
    "static-analysis",
}


def learning_root(brain: Path) -> Path:
    return brain / "learning"


def incidents_dir(brain: Path) -> Path:
    return learning_root(brain) / "incidents"


def lessons_dir(brain: Path, status: str = "") -> Path:
    base = learning_root(brain) / "lessons"
    return base / status if status else base


def ensure_dirs(brain: Path) -> None:
    for sub in ["incidents", "lessons/pending", "lessons/approved",
                "lessons/active", "lessons/deprecated", "lessons/rejected",
                "summaries"]:
        (learning_root(brain) / sub).mkdir(parents=True, exist_ok=True)


# ── YAML frontmatter helpers ──────────────────────────────────────────────────

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body) from a document with --- delimiters."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_text = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    fm: dict = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                inner = v[1:-1]
                fm[k.strip()] = [x.strip() for x in inner.split(",") if x.strip()]
            else:
                fm[k.strip()] = v
    return fm, body


def _render_frontmatter(fm: dict, body: str) -> str:
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(v)}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(body.lstrip("\n"))
    return "\n".join(lines)


# ── ID generation ──────────────────────────────────────────────────────────────

def _make_id(prefix: str) -> str:
    today = date.today().strftime("%Y%m%d")
    suffix = hashlib.sha1(os.urandom(8)).hexdigest()[:8]
    return f"{prefix}-{today}-{suffix}"


def new_incident_id() -> str:
    return _make_id("inc")


def new_lesson_id() -> str:
    return _make_id("les")


# ── Incident I/O ──────────────────────────────────────────────────────────────

def write_incident(brain: Path, inc: dict, evidence: str = "", root_cause: str = "",
                   fix: str = "") -> Path:
    ensure_dirs(brain)
    inc_id = inc.get("id") or new_incident_id()
    inc["id"] = inc_id
    body_parts = []
    if evidence:
        body_parts.append(f"## Evidence\n{evidence}")
    if root_cause:
        body_parts.append(f"## Root Cause\n{root_cause}")
    if fix:
        body_parts.append(f"## Fix\n{fix}")
    body = "\n\n".join(body_parts)
    content = _render_frontmatter(inc, body)
    path = incidents_dir(brain) / f"{inc_id}.md"
    path.write_text(content, encoding="utf-8")
    return path


def read_incident(brain: Path, inc_id: str) -> tuple[dict, str] | None:
    path = incidents_dir(brain) / f"{inc_id}.md"
    if not path.exists():
        return None
    return _parse_frontmatter(path.read_text(encoding="utf-8"))


def list_incidents(brain: Path) -> list[dict]:
    d = incidents_dir(brain)
    if not d.exists():
        return []
    result = []
    for f in sorted(d.glob("inc-*.md")):
        fm, _ = _parse_frontmatter(f.read_text(encoding="utf-8"))
        result.append(fm)
    return result


def amend_incident(brain: Path, inc_id: str,
                   root_cause: str = "", fix: str = "") -> tuple[bool, str]:
    """Append or replace Root Cause / Fix sections in an existing incident."""
    result = read_incident(brain, inc_id)
    if result is None:
        return False, f"Incident not found: {inc_id}"

    fm, body = result

    def _set_section(text: str, heading: str, content: str) -> str:
        import re
        pattern = rf"(## {re.escape(heading)}\n)(.*?)(?=\n## |\Z)"
        replacement = f"## {heading}\n{content}\n"
        if re.search(pattern, text, re.DOTALL):
            return re.sub(pattern, replacement, text, flags=re.DOTALL)
        return text.rstrip("\n") + f"\n\n## {heading}\n{content}\n"

    if root_cause:
        body = _set_section(body, "Root Cause", root_cause)
    if fix:
        body = _set_section(body, "Fix", fix)

    path = incidents_dir(brain) / f"{inc_id}.md"
    path.write_text(_render_frontmatter(fm, body), encoding="utf-8")
    return True, f"Incident {inc_id} amended."


# ── Lesson I/O ─────────────────────────────────────────────────────────────────

def _lesson_path(brain: Path, lesson_id: str, status: str | None = None) -> Path | None:
    """Find lesson file by searching all status subdirs (or a specific one)."""
    sub_dirs = [status] if status else ["pending", "approved", "active", "deprecated", "rejected"]
    for sub in sub_dirs:
        p = lessons_dir(brain, sub) / f"{lesson_id}.md"
        if p.exists():
            return p
    return None


def write_lesson(brain: Path, les: dict, body: str = "") -> Path:
    ensure_dirs(brain)
    les_id = les.get("id") or new_lesson_id()
    les["id"] = les_id
    status = les.get("status", "pending")
    content = _render_frontmatter(les, body)
    # Create 'rejected' dir if needed
    sub = lessons_dir(brain, status)
    sub.mkdir(parents=True, exist_ok=True)
    path = sub / f"{les_id}.md"
    path.write_text(content, encoding="utf-8")
    return path


def read_lesson(brain: Path, lesson_id: str) -> tuple[dict, str] | None:
    path = _lesson_path(brain, lesson_id)
    if path is None:
        return None
    return _parse_frontmatter(path.read_text(encoding="utf-8"))


def transition_lesson(brain: Path, lesson_id: str, new_status: str,
                      approved_by: str = "") -> tuple[bool, str]:
    """Move a lesson to a new status. Returns (ok, message)."""
    if new_status not in _VALID_STATUSES:
        return False, f"Invalid status: {new_status}"

    result = read_lesson(brain, lesson_id)
    if result is None:
        return False, f"Lesson not found: {lesson_id}"

    fm, body = result
    old_status = fm.get("status", "pending")

    # High-severity gate: must pass through approve step before activate
    if new_status == "active" and fm.get("severity") == "high":
        if old_status != "approved" or not fm.get("approved_by"):
            return False, (
                f"Lesson {lesson_id} has severity=high and requires arbiter approval first.\n"
                "Run: brain-learn approve <id> --as <arbiter-agent-id>"
            )

    # Duplicate gate: block activation when an equivalent active lesson already exists
    if new_status == "active":
        dup = find_duplicate_active(brain, fm.get("rule", ""), exclude_id=lesson_id)
        if dup:
            return False, (
                f"Duplicate lesson detected: {dup.get('id')} already active with the same rule.\n"
                "Deprecate or amend the existing lesson before activating this one."
            )

    # Remove from old location
    old_path = _lesson_path(brain, lesson_id, old_status)
    if old_path and old_path.exists():
        old_path.unlink()

    fm["status"] = new_status
    fm["updated"] = date.today().isoformat()
    if approved_by:
        fm["approved_by"] = approved_by

    write_lesson(brain, fm, body)
    return True, f"Lesson {lesson_id}: {old_status} → {new_status}"


def list_lessons(brain: Path, status: str = "") -> list[dict]:
    statuses = [status] if status else ["pending", "approved", "active", "deprecated"]
    result = []
    for sub in statuses:
        d = lessons_dir(brain, sub)
        if not d.exists():
            continue
        for f in sorted(d.glob("les-*.md")):
            fm, _ = _parse_frontmatter(f.read_text(encoding="utf-8"))
            result.append(fm)
    return result


# ── Prompt injection helpers ───────────────────────────────────────────────────

_MAX_LESSONS = 5
_MAX_TOKENS = 800


def _rough_token_count(text: str) -> int:
    return max(1, len(text) // 4)


def select_lessons_for_injection(brain: Path, role: str,
                                 tags: list[str] | None = None) -> list[dict]:
    """Return up to MAX_LESSONS active lessons ranked for the given role."""
    active = list_lessons(brain, "active")
    candidates = []
    for les in active:
        if is_expired(les):
            continue
        roles = les.get("roles", [])
        if isinstance(roles, str):
            roles = [r.strip() for r in roles.split(",")]
        if role not in roles:
            continue
        score = 0
        if tags:
            les_tags = les.get("tags", [])
            if isinstance(les_tags, str):
                les_tags = [t.strip() for t in les_tags.split(",")]
            score += len(set(tags) & set(les_tags)) * 2
        sev = les.get("severity", "low")
        score += {"high": 3, "medium": 2, "low": 1}.get(sev, 0)
        candidates.append((score, les))

    candidates.sort(key=lambda x: -x[0])
    result: list[dict] = []
    used_tokens = 0
    for _, les in candidates[:_MAX_LESSONS]:
        rule = les.get("rule", "")
        if not rule:
            continue
        tokens = _rough_token_count(rule)
        if used_tokens + tokens > _MAX_TOKENS:
            break
        result.append(les)
        used_tokens += tokens

    return result


def render_injection_block(lessons: list[dict]) -> str:
    if not lessons:
        return ""
    lines = ["# === LEARNED LESSONS ==="]
    for i, les in enumerate(lessons, 1):
        rule = les.get("rule", "").strip()
        les_id = les.get("id", "")
        lines.append(f"{i}. [{les_id}] {rule}")
    return "\n".join(lines) + "\n"


# ── Quality controls ──────────────────────────────────────────────────────────

_STOPWORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would should could may might shall must not no nor so yet "
    "and or but if then else when while for of in on at to with from".split()
)


def _normalize_rule(rule: str) -> str:
    """Return a stable fingerprint for duplicate detection."""
    words = re.sub(r"[^\w\s]", " ", rule.lower()).split()
    sig = sorted(w for w in words if w not in _STOPWORDS and len(w) > 1)
    return " ".join(sig)


def find_duplicate_active(brain: Path, rule: str,
                          exclude_id: str = "") -> dict | None:
    """Return the first active lesson with the same normalised rule, or None."""
    sig = _normalize_rule(rule)
    if not sig:
        return None
    for les in list_lessons(brain, "active"):
        if les.get("id") == exclude_id:
            continue
        if _normalize_rule(les.get("rule", "")) == sig:
            return les
    return None


def check_wiki_conflict(brain: Path, rule: str) -> list[str]:
    """Return titles of human-curated wiki pages whose content overlaps the rule."""
    wiki = brain / "wiki"
    if not wiki.exists():
        return []
    rule_lower = rule.lower()
    # Extract significant keywords from the rule (non-stopword tokens ≥4 chars)
    keywords = {w for w in re.sub(r"[^\w\s]", " ", rule_lower).split()
                if w not in _STOPWORDS and len(w) >= 4}
    if not keywords:
        return []
    conflicts: list[str] = []
    for md in wiki.glob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, _ = _parse_frontmatter(text)
        if not (fm.get("curation") == "human" or fm.get("protected")):
            continue
        text_lower = text.lower()
        if sum(1 for kw in keywords if kw in text_lower) >= max(1, len(keywords) // 2):
            conflicts.append(fm.get("title") or md.stem)
    return conflicts


def is_expired(fm: dict) -> bool:
    """True if the lesson has an 'expires' field that is in the past."""
    exp = fm.get("expires", "")
    if not exp:
        return False
    try:
        return date.fromisoformat(str(exp)) < date.today()
    except ValueError:
        return False


def prune_expired_lessons(brain: Path) -> list[str]:
    """Transition all expired active lessons to deprecated. Returns list of ids."""
    pruned = []
    for les in list_lessons(brain, "active"):
        if is_expired(les):
            les_id = les.get("id", "")
            ok, _ = transition_lesson(brain, les_id, "deprecated")
            if ok:
                pruned.append(les_id)
    return pruned
