"""search_inject.renderers — ready-made ``html -> text`` renderers for the ``render=``
dial of :func:`make_web_fetch_tool`, so your injected page and the real pages a model
fetches are extracted by ONE calibrated fetcher (no fetcher-artifact confound).

These emulate what each provider's NATIVE fetch tool hands the model, reverse-engineered
by probing the tools on known pages:

  * ``render_claude_style`` — cleaned markdown-like body text **plus a ``<meta>`` header**
    (``title``, ``og:*``, ``twitter:*``, ``article:*`` …). Mirrors Claude ``web_fetch``.
    Excludes JSON-LD, raw ``<script>``/``<style>``, element classes.
  * ``render_gemini_style`` — the same cleaned body text **+ ``<title>`` only, no ``<meta>``**.
    Mirrors Gemini ``url_context``, which returns text-only content.
  * ``render_html`` — most permissive: lightly-slimmed raw HTML (keeps JSON-LD, every
    ``<meta>``, classes, the full DOM). For raw-HTML-passthrough setups.

The one emulation-critical difference between the two natives is the ``<meta>`` header —
Claude surfaces it, Gemini doesn't — and it carries the brand/publisher signals that drive
Claude's chrome-sensitivity vs Gemini's format-blindness. Pick the renderer that matches
the model you're testing, or use one uniformly to hold the fetcher constant across a
cross-model comparison.

Requires the optional ``render`` extra (BeautifulSoup + html2text)::

    pip install search-inject[render]

The pure-``requests`` core has no such dependency; these are imported lazily so importing
the package never forces the extra.
"""
import re

import requests

from .backends import UA

DEFAULT_CAP = 80_000
# Cap raw HTML before parsing. Agents fetch many large real pages; parsing full multi-MB docs through
# BeautifulSoup+html2text is CPU-pathological (seconds/page, 100% CPU) — yet the output is truncated to
# a few KB and the article body + <meta> head sit near the top, so the first 300KB is more than enough.
# Output-neutral in practice (byte-identical usable prefix); turns each parse from seconds to ms.
MAX_PARSE_BYTES = 300_000


def _need():
    try:
        from bs4 import BeautifulSoup
        import html2text
    except ImportError as e:                       # pragma: no cover - dependency hint
        raise ImportError("search_inject.renderers needs the 'render' extra: "
                          "pip install search-inject[render]  (beautifulsoup4 + html2text)") from e
    return BeautifulSoup, html2text


def _get(url, timeout=30):
    """url -> raw HTML. Default fetcher for the ``get=`` slot of make_web_fetch_tool."""
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    return r.text


def _cap(out, max_chars):
    return out if len(out) <= max_chars else out[:max_chars] + f"\n[... truncated at {max_chars} chars ...]"


def readable_text(html):
    """The cleaned, markdown-ish body text both natives deliver: visible page text as prose.
    Keeps visible chrome (masthead, byline, dateline, "Related", ad labels — natives include
    these); drops non-visible structure (head, scripts, styles, iframes, svg)."""
    BeautifulSoup, html2text = _need()
    soup = BeautifulSoup(html[:MAX_PARSE_BYTES], "html.parser")   # bound pathological tail-parsing
    if soup.head:
        soup.head.decompose()
    for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
        tag.decompose()
    body = soup.body or soup
    h = html2text.HTML2Text()
    h.ignore_links = True        # natives deliver prose, not a link map
    h.ignore_images = True
    h.body_width = 0
    return re.sub(r"\n{3,}", "\n\n", h.handle(str(body)).strip())


def meta_header(html):
    """Claude-only ``<meta>`` block in Claude's ``meta-<key>: value`` format, plus ``title``.
    Covers ``og:*``, ``twitter:*``, ``name=*``, ``article:*``; excludes JSON-LD and classes
    (Claude does not surface those)."""
    BeautifulSoup, _ = _need()
    soup = BeautifulSoup(html[:MAX_PARSE_BYTES], "html.parser")   # head/meta live at the top → safe
    lines = []
    if soup.title and soup.title.string:
        lines.append(f"title: {soup.title.string.strip()}")
    for m in soup.find_all("meta"):
        key = m.get("property") or m.get("name")
        content = m.get("content")
        if key and content:
            lines.append(f"meta-{key}: {content}")
    return "\n".join(lines)


# ── html -> text renderers (feed to make_web_fetch_tool(render=...)) ───────────
def render_claude_style(html, max_chars=DEFAULT_CAP):
    """HTML -> Claude-style text: ``<meta>`` header + body. Emulates Claude ``web_fetch``."""
    return _cap(meta_header(html) + "\n\n---\n\n" + readable_text(html), max_chars)


def render_gemini_style(html, max_chars=DEFAULT_CAP):
    """HTML -> Gemini-style text: ``<title>`` + body, no ``<meta>``. Emulates ``url_context``."""
    BeautifulSoup, _ = _need()
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    body = readable_text(html)
    return _cap((f"title: {title}\n\n{body}") if title else body, max_chars)


def render_html(html, max_chars=80_000):
    """HTML -> lightly-slimmed raw HTML: keep JSON-LD, every ``<meta>``, classes, full DOM;
    strip only ``<script>`` (except ld+json), ``<style>``, ``<noscript>``, ``<iframe>``.
    The most permissive renderer — exposes structure the native emulators drop. No bs4 needed."""
    def _keep_script(m):
        s = m.group(0)
        return s if 'application/ld+json' in s else ""
    html = re.sub(r'<script\b[^>]*>.*?</script>', _keep_script, html, flags=re.DOTALL)
    html = re.sub(r'<style(?:\s[^>]*)?>.*?</style>', '', html, flags=re.DOTALL)
    html = re.sub(r'<noscript\b[^>]*>.*?</noscript>', '', html, flags=re.DOTALL)
    html = re.sub(r'<iframe\b[^>]*>.*?</iframe>', '', html, flags=re.DOTALL)
    html = re.sub(r'<iframe\b[^>]*/>', '', html)
    html = re.sub(r'[ \t]+', ' ', html)
    html = re.sub(r'\n{3,}', '\n\n', html)
    return _cap(html, max_chars)


# ── url -> text convenience (get + render in one call) ─────────────────────────
def fetch_claude_style(url, max_chars=DEFAULT_CAP):
    """Fetch `url` live and render Claude-style (text + ``<meta>`` header)."""
    return render_claude_style(_get(url), max_chars)


def fetch_gemini_style(url, max_chars=DEFAULT_CAP):
    """Fetch `url` live and render Gemini-style (text + ``<title>``, no ``<meta>``)."""
    return render_gemini_style(_get(url), max_chars)
