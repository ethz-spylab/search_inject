"""Tests for search_inject.fetch.make_web_fetch_tool.

Two modes are covered:
  * LEGACY (render=None): injected content served verbatim; real pages via real_fetch.
  * CONSISTENT (render=fn): injected HTML and real pages both routed through one renderer.

All real-page fetching is stubbed (get / real_fetch), so tests are network-free.
"""
from search_inject import make_web_fetch_tool

U = "https://example.com/mine/"
OTHER = "https://competitor.com/story"


# ── legacy mode ───────────────────────────────────────────────────────────────
def test_legacy_injected_served_verbatim():
    _, h = make_web_fetch_tool([U], contents={U: "MY TEXT"})
    assert h(U) == "MY TEXT"


def test_legacy_injected_empty_is_no_content():
    _, h = make_web_fetch_tool([U], contents={U: ""})
    assert "no readable content" in h(U)


def test_legacy_refuse_blocks_unknown():
    _, h = make_web_fetch_tool([U], contents={U: "x"}, on_unknown="refuse")
    assert "Could not fetch" in h(OTHER)


def test_legacy_passthrough_calls_real_fetch():
    seen = []

    def rf(url, timeout):
        seen.append(url)
        return f"REAL:{url}"

    _, h = make_web_fetch_tool([U], contents={U: "x"}, real_fetch=rf)
    assert h(OTHER) == f"REAL:{OTHER}"
    assert seen == [OTHER]


# ── url normalization (query / fragment / case / trailing slash) ──────────────
def test_injected_match_ignores_query_fragment_slash():
    _, h = make_web_fetch_tool([U], contents={U: "MINE"})
    assert h("https://example.com/mine") == "MINE"
    assert h("https://example.com/mine/?utm_source=chatgpt") == "MINE"
    assert h("https://example.com/mine#section") == "MINE"


# ── consistent mode (render) ──────────────────────────────────────────────────
def test_consistent_injected_goes_through_render():
    _, h = make_web_fetch_tool([U], contents={U: "<b>hi</b>"}, render=lambda html: f"R[{html}]")
    assert h(U) == "R[<b>hi</b>]"


def test_consistent_real_page_fetched_then_rendered():
    _, h = make_web_fetch_tool([U], contents={U: "<b>hi</b>"},
                               render=lambda html: f"R[{html}]",
                               get=lambda url: f"HTML_OF:{url}")
    assert h(OTHER) == f"R[HTML_OF:{OTHER}]"


def test_consistent_render_takes_precedence_over_real_fetch():
    def rf(url, timeout):
        raise AssertionError("real_fetch must be ignored when render is set")

    _, h = make_web_fetch_tool([U], contents={U: "x"},
                               render=lambda html: f"R[{html}]",
                               get=lambda url: "GH", real_fetch=rf)
    assert h(OTHER) == "R[GH]"


def test_same_renderer_for_injected_and_real():
    """The fairness guarantee: injected and real pages come back through the SAME renderer."""
    calls = []

    def render(html):
        calls.append(html)
        return "RENDERED"

    _, h = make_web_fetch_tool([U], contents={U: "<i>ours</i>"},
                               render=render, get=lambda url: "<i>theirs</i>")
    assert h(U) == "RENDERED"
    assert h(OTHER) == "RENDERED"
    assert calls == ["<i>ours</i>", "<i>theirs</i>"]   # both went through render


# ── error handling ────────────────────────────────────────────────────────────
def test_fetch_exception_is_reported_not_raised():
    def boom(url):
        raise RuntimeError("network down")

    _, h = make_web_fetch_tool([U], contents={U: "x"}, render=lambda h: h, get=boom)
    out = h(OTHER)
    assert "Could not fetch" in out and "RuntimeError" in out


# ── schema shape per provider ─────────────────────────────────────────────────
def test_schema_shapes_per_provider():
    s_openai, _ = make_web_fetch_tool([U], provider="openai", contents={U: "x"})
    assert s_openai["type"] == "function" and s_openai["function"]["name"] == "web_fetch"

    s_anthropic, _ = make_web_fetch_tool([U], provider="anthropic", contents={U: "x"})
    assert "input_schema" in s_anthropic and s_anthropic["name"] == "web_fetch"

    s_gemini, _ = make_web_fetch_tool([U], provider="gemini", contents={U: "x"})
    assert "function_declarations" in s_gemini
