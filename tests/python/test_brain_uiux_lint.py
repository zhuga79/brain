"""t-2026-06-29-uiux-lint-gate: zero-dep UI anti-pattern linter."""
import brain_uiux_lint as L


def test_extract_css():
    assert "x" in L.extract_css("<style>.a{x:1}</style>")
    assert L.extract_css("<p>no style</p>") == ""


def test_contrast_ratio_known():
    # black on white = 21:1
    assert L.contrast_ratio((0, 0, 0), (255, 255, 255)) == 21.0


def test_parse_color_forms():
    assert L._parse_color("#fff") == (255, 255, 255)
    assert L._parse_color("#102f35") == (16, 47, 53)
    assert L._parse_color("rgba(50, 96, 118, .18)") == (50, 96, 118)
    assert L._parse_color("nonsense") is None


def test_side_tab_flagged():
    f = L.check_side_tab(".card{border-left: 3px solid #9bc8ff; border-radius:6px}")
    assert len(f) == 1 and f[0]["rule"] == "side-tab"


def test_side_tab_thin_border_ok():
    assert L.check_side_tab(".x{border-left: 1px solid #ccc}") == []


def test_single_font_flagged():
    f = L.check_single_font("body{font-family: 'SFMono-Regular', monospace}")
    assert f and f[0]["rule"] == "single-font"


def test_two_fonts_ok():
    css = "h1{font-family:Geist} p{font-family:Satoshi}"
    assert L.check_single_font(css) == []


def test_tight_leading_flagged():
    f = L.check_tight_leading(".h{line-height: 1.0;}")
    assert f and f[0]["rule"] == "tight-leading"


def test_low_contrast_flagged():
    f = L.check_low_contrast(".m{color:#888; background:#999;}")
    assert f and f[0]["rule"] == "low-contrast"


def test_low_contrast_ok():
    assert L.check_low_contrast(".ok{color:#000; background:#fff;}") == []


def test_lint_html_allowlist_default():
    # noise rules are not implemented/ported; allowlist is a no-op guard
    html = "<style>.c{border-left:4px solid #f00}</style>"
    out = L.lint_html(html)
    assert any(f["rule"] == "side-tab" for f in out)


def test_apply_baseline_rule_only():
    findings = [{"rule": "single-font", "detail": "x"}, {"rule": "side-tab", "selector": ".a"}]
    out = L.apply_baseline(findings, [{"rule": "single-font", "reason": "intentional"}])
    assert [f["rule"] for f in out] == ["side-tab"]


def test_apply_baseline_rule_and_selector():
    findings = [{"rule": "tight-leading", "selector": ".metric-card strong"},
                {"rule": "tight-leading", "selector": ".other"}]
    out = L.apply_baseline(findings, [{"rule": "tight-leading", "selector": ".metric-card strong"}])
    assert [f["selector"] for f in out] == [".other"]


def test_load_baseline_missing(tmp_path):
    assert L.load_baseline(str(tmp_path / "nope.json")) == []


def test_lint_html_with_baseline():
    html = "<style>.c{border-left:4px solid #f00} body{font-family:monospace}</style>"
    base = [{"rule": "side-tab"}]
    out = L.lint_html(html, baseline=base)
    assert all(f["rule"] != "side-tab" for f in out)
