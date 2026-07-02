"""search_inject.fetch — the *fetch* layer, mirroring core.make_web_search_tool.

`make_web_fetch_tool(inject_urls, contents=...)` returns a `(schema, handler)` pair
for a `web_fetch` tool. When the model fetches one of our URLs the handler returns
our CONTROLLED full-page text (no hosting required — nothing is on the open web);
for any other URL it either passes through to a real fetch or refuses.

Pairs with make_web_search_tool: the search tool injects the SERP snippet, the fetch
tool injects the full article body — so a model can search → see our hit → fetch →
read the full page, exactly as it would for a real result. This is what lets the
in-the-wild probe parallel the lab study (v6.2.1), where the model read the full page.

`on_unknown`:
  'passthrough' — really fetch other URLs (faithful in-the-wild; lets the model
                  triangulate against real pages too — use for realism).
  'refuse'      — other URLs return "unavailable" (isolates the lever: the model's
                  view is limited to the injected page(s); use for a clean test).
"""
import re
import requests

from .backends import UA

FETCH_NAME = "web_fetch"
FETCH_DESC = ("Fetch the full readable text content of a web page given its URL. "
              "Use after web_search to read a result in full.")
_FETCH_PARAMS = {
    "type": "object",
    "properties": {"url": {"type": "string", "description": "The URL of the page to fetch."}},
    "required": ["url"],
}


def fetch_schema(provider):
    if provider == "anthropic":
        return {"name": FETCH_NAME, "description": FETCH_DESC, "input_schema": _FETCH_PARAMS}
    if provider == "openai":
        return {"type": "function",
                "function": {"name": FETCH_NAME, "description": FETCH_DESC, "parameters": _FETCH_PARAMS}}
    if provider == "gemini":
        return {"function_declarations": [
            {"name": FETCH_NAME, "description": FETCH_DESC, "parameters": _FETCH_PARAMS}]}
    raise ValueError(provider)


def _norm(u):
    return (u or "").split("#")[0].split("?")[0].rstrip("/").lower()


def _readable(url, timeout):
    html = requests.get(url, headers={"User-Agent": UA}, timeout=timeout).text
    text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:6000]


def make_web_fetch_tool(inject_urls, *, provider="openai", contents=None,
                        on_unknown="passthrough", real_fetch=None, timeout=20,
                        render=None, get=None):
    """inject_urls : URLs we control the content of.
    provider      : 'anthropic'|'openai'|'gemini' — shape of the returned tool schema
                    (same three as make_web_search_tool).
    contents      : {url: page}. In LEGACY mode (render=None) this is the final text served
                    verbatim. In CONSISTENT mode (render given) it is raw HTML, run through
                    `render` just like a real page — so injected and real pages get the SAME
                    extraction and no behavioural difference can be blamed on the fetcher.
    on_unknown    : 'passthrough' (real fetch) | 'refuse' (other URLs return "unavailable").
    real_fetch    : LEGACY-mode live fetcher, url->text (default: the built-in `_readable`).
    timeout       : seconds for the default live GET (used by `_readable` / the default `get`).
    render        : html->text renderer applied UNIFORMLY to injected HTML and to real-page
                    HTML — the "one fetcher for all pages" fairness dial. Pass e.g.
                    search_inject.render_claude_style. When set, `real_fetch` is ignored (real
                    pages are fetched by `get` then rendered).
    get           : CONSISTENT-mode raw fetcher, url->html (default: a plain requests GET).
    returns       : (schema, handler) where handler(url)->str.
    """
    contents = contents or {}
    inj = {_norm(u): contents.get(u, "") for u in inject_urls}
    no_content = lambda url: f"Could not fetch {url}: the page returned no readable content."

    def _default_get(url):
        return requests.get(url, headers={"User-Agent": UA}, timeout=timeout).text
    getter = get or _default_get

    def handler(url: str):
        key = _norm(url)
        if key in inj:                              # our page — never leak past this branch
            raw = inj[key]
            if not raw:
                return no_content(url)
            return render(raw) if render else raw   # consistent: our HTML through the shared renderer
        if on_unknown == "refuse":
            return no_content(url)
        try:
            if render:                              # consistent: real page through the SAME renderer
                return render(getter(url))
            return (real_fetch or _readable)(url, timeout)   # legacy: verbatim/crude passthrough
        except Exception as e:
            return f"Could not fetch {url}: {type(e).__name__}: {e}"

    return fetch_schema(provider), handler
