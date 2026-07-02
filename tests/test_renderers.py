"""Tests for search_inject.renderers — the calibrated html->text renderers.

Pure functions over a fixed HTML string: no network, fully deterministic.
`render_claude_style` / `render_gemini_style` need the `render` extra (bs4 + html2text);
`render_html` does not.
"""
from search_inject import (render_claude_style, render_gemini_style, render_html,
                           readable_text, meta_header)

HTML = """<!DOCTYPE html><html><head>
<title>My Headline</title>
<meta property="og:title" content="OG Headline">
<meta name="twitter:site" content="@example">
<meta property="article:published_time" content="2026-07-02T09:00:00Z">
<script type="application/ld+json">{"@type":"NewsArticle"}</script>
<script>var tracker = 1;</script>
<style>.x{color:red}</style>
</head><body>
<h1>My Headline</h1>
<p>By Jane Doe, Example News</p>
<p>The body paragraph with a distinctive FINGERPRINT_XYZ token.</p>
<nav>Home About</nav>
</body></html>"""


def test_readable_text_keeps_body_drops_code():
    t = readable_text(HTML)
    assert "FINGERPRINT_XYZ" in t          # body prose kept
    assert "Jane Doe" in t                 # visible byline kept
    assert "tracker" not in t              # <script> stripped
    assert "color:red" not in t            # <style> stripped


def test_meta_header_format_and_exclusions():
    m = meta_header(HTML)
    assert "title: My Headline" in m
    assert "meta-og:title: OG Headline" in m
    assert "meta-twitter:site: @example" in m
    assert "meta-article:published_time: 2026-07-02T09:00:00Z" in m
    assert "ld+json" not in m              # JSON-LD not surfaced by Claude


def test_claude_style_has_meta_and_body():
    out = render_claude_style(HTML)
    assert "meta-og:title" in out          # meta header present
    assert "FINGERPRINT_XYZ" in out        # body present
    assert "---" in out                    # header/body separator


def test_gemini_style_title_and_body_but_no_meta():
    out = render_gemini_style(HTML)
    assert "title: My Headline" in out
    assert "FINGERPRINT_XYZ" in out
    assert "meta-og:title" not in out      # NO <meta> block
    assert "meta-twitter" not in out


def test_claude_vs_gemini_the_meta_difference():
    """The one emulation-critical difference: Claude surfaces <meta>, Gemini does not."""
    c, g = render_claude_style(HTML), render_gemini_style(HTML)
    assert "@example" in c and "@example" not in g


def test_render_html_keeps_structure_strips_code():
    out = render_html(HTML)
    assert "ld+json" in out                # JSON-LD kept (permissive)
    assert "og:title" in out               # raw <meta> kept
    assert "FINGERPRINT_XYZ" in out
    assert "var tracker" not in out        # plain <script> stripped
    assert "color:red" not in out          # <style> stripped


def test_cap_truncates():
    out = render_html("<body>" + "x" * 200 + "</body>", max_chars=30)
    assert "truncated" in out
    assert len(out) < 120
