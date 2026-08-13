"""brain_uiux_lint — zero-dep UI anti-pattern linter for generated HTML.

Python port of the high-signal deterministic subset of impeccable's detector
(Apache-2.0, github.com/pbakaus/impeccable), chosen via PoC
t-2026-06-29-uiux-detector-poc. Rules: side-tab, single-font, tight-leading,
low-contrast. Noise rules (design-system-color, em-dash, numbered-markers) are
intentionally NOT ported. See doctrine/design-review-workflow.md.
"""
from __future__ import annotations

import re
from typing import Any

# --- CSS extraction -------------------------------------------------------
_STYLE_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_GENERIC_FONTS = {"monospace", "sans-serif", "serif", "system-ui", "ui-monospace",
                  "ui-sans-serif", "inherit", "initial", "unset"}


def extract_css(html: str) -> str:
    """Return concatenated contents of all <style> blocks."""
    return "\n".join(m.group(1) for m in _STYLE_RE.finditer(html))


def _rules(css: str) -> list[tuple[str, str]]:
    return [(m.group(1).strip(), m.group(2)) for m in _RULE_RE.finditer(css)]


# --- color math (WCAG) ----------------------------------------------------
def _parse_color(tok: str) -> tuple[int, int, int] | None:
    tok = tok.strip().lower()
    m = re.fullmatch(r"#([0-9a-f]{3})", tok)
    if m:
        h = m.group(1)
        return tuple(int(c * 2, 16) for c in h)  # type: ignore
    m = re.fullmatch(r"#([0-9a-f]{6})", tok)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = re.match(r"rgba?\(\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)", tok)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _lum(rgb: tuple[int, int, int]) -> float:
    def ch(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast_ratio(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    l1, l2 = _lum(c1), _lum(c2)
    hi, lo = max(l1, l2), min(l1, l2)
    return round((hi + 0.05) / (lo + 0.05), 2)


# --- rules ----------------------------------------------------------------
def check_side_tab(css: str) -> list[dict[str, Any]]:
    """border-left/right >1px used as a colored accent (AI tell)."""
    out = []
    for sel, body in _rules(css):
        for m in re.finditer(r"border-(left|right):\s*([0-9.]+)px([^;}]*)", body, re.I):
            width = float(m.group(2)); rest = m.group(3).lower()
            visible = ("transparent" not in rest and "none" not in rest
                       and re.search(r"solid|dashed|dotted|double|#[0-9a-f]{3,6}|rgba?\(|var\(", rest))
            if width > 1 and visible:
                out.append({"rule": "side-tab", "severity": "warning",
                            "selector": sel, "detail": f"border-{m.group(1)}: {width}px accent"})
    return out


def check_single_font(css: str) -> list[dict[str, Any]]:
    fams = set()
    for m in re.finditer(r"font-family:\s*([^;}]+)", css, re.I):
        first = m.group(1).split(",")[0].strip().strip('"\'').lower()
        if first and first not in _GENERIC_FONTS:
            fams.add(first)
    if len(fams) <= 1:
        return [{"rule": "single-font", "severity": "warning",
                 "detail": f"only font family: {sorted(fams) or ['<none>']}"}]
    return []


def check_tight_leading(css: str) -> list[dict[str, Any]]:
    out = []
    for sel, body in _rules(css):
        for m in re.finditer(r"line-height:\s*([0-9.]+)\s*;", body, re.I):
            lh = float(m.group(1))
            if lh < 1.2:  # unitless tight leading
                out.append({"rule": "tight-leading", "severity": "warning",
                            "selector": sel, "detail": f"line-height: {lh}"})
    return out


def check_low_contrast(css: str, threshold: float = 4.5) -> list[dict[str, Any]]:
    """Selectors declaring both color and background(-color) as resolvable colors."""
    out = []
    for sel, body in _rules(css):
        cm = re.search(r"(?<!-)color:\s*([^;]+)", body, re.I)
        bm = re.search(r"background(?:-color)?:\s*([^;]+)", body, re.I)
        if not (cm and bm):
            continue
        fg = _parse_color(cm.group(1).strip().split()[0]) if cm.group(1).strip().split() else None
        bg = None
        for tok in bm.group(1).split():
            bg = _parse_color(tok)
            if bg:
                break
        if fg and bg:
            cr = contrast_ratio(fg, bg)
            if cr < threshold:
                out.append({"rule": "low-contrast", "severity": "warning",
                            "selector": sel, "detail": f"contrast {cr}:1 (< {threshold})"})
    return out


_DEFAULT_ALLOW = {"design-system-color", "em-dash-overuse", "numbered-section-markers"}


def apply_baseline(findings: list[dict[str, Any]],
                   suppressions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop findings matching a baseline suppression.

    A suppression {rule, selector?} matches a finding when the rule is equal and
    (the suppression has no selector OR its selector equals the finding's).
    """
    def suppressed(f: dict[str, Any]) -> bool:
        for sup in suppressions:
            if sup.get("rule") != f["rule"]:
                continue
            sel = sup.get("selector")
            if sel is None or sel == f.get("selector"):
                return True
        return False
    return [f for f in findings if not suppressed(f)]


def load_baseline(path: str) -> list[dict[str, Any]]:
    """Load a baseline JSON ({\"suppressions\": [...]}). Missing file -> []."""
    import json, os
    if not os.path.exists(path):
        return []
    try:
        return json.loads(open(path, encoding="utf-8").read()).get("suppressions", [])
    except (OSError, ValueError):
        return []


def lint_html(html: str, allow: set[str] | None = None,
              baseline: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    css = extract_css(html)
    allow = (_DEFAULT_ALLOW if allow is None else allow)
    findings: list[dict[str, Any]] = []
    findings += check_side_tab(css)
    findings += check_single_font(css)
    findings += check_tight_leading(css)
    findings += check_low_contrast(css)
    findings = [f for f in findings if f["rule"] not in allow]
    if baseline:
        findings = apply_baseline(findings, baseline)
    return findings
