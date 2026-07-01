"""Pluggable real-search backends → list of {title, url, snippet}.

Each returns genuine web results for a query; the injected URLs are spliced in
on top by core.merge(). Bring your own API key. `null` returns nothing (useful
for the "ours only" condition or offline testing).
"""
import os
import requests

UA = "Mozilla/5.0 (compatible; SearchInject/1.0)"


def brave_search(query, api_key=None, count=8):
    """Brave Search API (api.search.brave.com). Free tier available.
    Nice choice because it's the suspected backend of some model web tools."""
    key = api_key or os.getenv("BRAVE_API_KEY")
    r = requests.get("https://api.search.brave.com/res/v1/web/search",
                     params={"q": query, "count": count},
                     headers={"X-Subscription-Token": key, "Accept": "application/json",
                              "User-Agent": UA}, timeout=20)
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("url", ""),
             "snippet": x.get("description", "")}
            for x in r.json().get("web", {}).get("results", [])]


def serper_search(query, api_key=None, count=8):
    """Serper.dev — Google results via API. Cheap."""
    key = api_key or os.getenv("SERPER_API_KEY")
    r = requests.post("https://google.serper.dev/search",
                      json={"q": query, "num": count},
                      headers={"X-API-KEY": key, "Content-Type": "application/json"},
                      timeout=20)
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("link", ""),
             "snippet": x.get("snippet", "")}
            for x in r.json().get("organic", [])]


def null_search(query, api_key=None, count=8):
    """No real results — injected URLs become the entire result set."""
    return []


def openai_search(query, api_key=None, count=8, model="gpt-4.1"):
    """Most faithful emulation of OpenAI/ChatGPT search: call OpenAI's OWN
    native `web_search` tool and return the results IT retrieved (url + title +
    the cited snippet span). Beats any Bing/DDG proxy because the results *are*
    OpenAI's actual search output. Needs OPENAI_API_KEY + the `openai` SDK."""
    from openai import OpenAI  # lazy import (keeps base deps to requests)
    c = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
    for ttype in ("web_search", "web_search_preview"):
        try:
            r = c.responses.create(model=model, tools=[{"type": ttype}],
                                   input=f"Search the web for: {query}")
            out, seen = [], set()
            for item in r.output:
                for cont in getattr(item, "content", []) or []:
                    text = getattr(cont, "text", "") or ""
                    for ann in getattr(cont, "annotations", []) or []:
                        url = getattr(ann, "url", None)
                        if not url or url in seen:
                            continue
                        seen.add(url)
                        s, e = getattr(ann, "start_index", 0), getattr(ann, "end_index", 0)
                        out.append({"title": getattr(ann, "title", "") or url,
                                    "url": url,
                                    "snippet": (text[s:e] if e > s else "")[:300]})
            return out[:count]
        except Exception:
            continue
    return []


def gemini_search(query, api_key=None, count=8):
    """Most faithful Gemini emulation: capture Gemini's OWN grounding (Google),
    resolve the vertexaisearch redirect URLs to the real page URLs, and pull the
    og:description snippet from the same fetch (one request per result). Gemini
    already grounds organically, so this is mainly for the calibration arm.
    Needs GOOGLE_API_KEY + the `google-genai` SDK."""
    import re as _re
    from google import genai  # lazy
    from google.genai import types
    g = genai.Client(api_key=api_key or os.getenv("GOOGLE_API_KEY"))
    r = g.models.generate_content(model="gemini-2.5-flash", contents=f"Search: {query}",
        config=types.GenerateContentConfig(tools=[{"google_search": {}}]))
    gm = getattr(r.candidates[0], "grounding_metadata", None)
    out = []
    for ch in (getattr(gm, "grounding_chunks", None) or [])[:count]:
        w = getattr(ch, "web", None)
        if not w or not getattr(w, "uri", None):
            continue
        title, url, snippet = getattr(w, "title", "") or "", w.uri, ""
        try:
            resp = requests.get(w.uri, allow_redirects=True, timeout=15,
                                headers={"User-Agent": UA})
            url = resp.url
            m = (_re.search(r'(?:property|name)=["\']og:description["\'][^>]*content=["\']([^"\']+)', resp.text)
                 or _re.search(r'name=["\']description["\'][^>]*content=["\']([^"\']+)', resp.text))
            if m:
                snippet = m.group(1)[:300]
        except Exception:
            pass
        out.append({"title": title, "url": url, "snippet": snippet})
    return out


_BACKENDS = {"brave": brave_search, "serper": serper_search,
             "openai": openai_search, "gemini": gemini_search, "null": null_search}


def get_backend(name, api_key=None):
    if callable(name):
        return name
    fn = _BACKENDS.get(name)
    if fn is None:
        raise ValueError(f"unknown backend {name!r}; choices: {list(_BACKENDS)}")
    return lambda query: fn(query, api_key)
