"""search_inject — drop chosen URLs into a model's web-search results.

Quick start:
    from search_inject import make_web_search_tool, format_results

    schema, handler = make_web_search_tool(
        ["https://example.com/my-page/"],
        provider="anthropic", backend="brave", backend_key=BRAVE_KEY, rank="top")

    # in your tool-use loop, when the model calls web_search(query):
    results = handler(query)                 # [{title,url,snippet}, ...]
    tool_result_text = format_results(results)

See README.md for the cross-model loop, the no-injection control, and the
Claude Code / Codex (MCP) notes.
"""
__version__ = "0.2.0"

from .core import make_web_search_tool, url_to_result, merge, camouflage
from .fetch import make_web_fetch_tool, fetch_schema, FETCH_NAME
from .tools import tool_schema, format_results, NAME
from .replicas import make_native_replica, REPLICAS
from .renderers import (render_claude_style, render_gemini_style, render_html,
                        fetch_claude_style, fetch_gemini_style, readable_text, meta_header)
from .backends import (get_backend, brave_search, serper_search,
                       openai_search, gemini_search, null_search)

__all__ = ["__version__",
           "make_web_search_tool", "url_to_result", "merge", "camouflage",
           "make_web_fetch_tool", "fetch_schema", "FETCH_NAME",
           "tool_schema", "format_results", "NAME",
           "make_native_replica", "REPLICAS",
           "render_claude_style", "render_gemini_style", "render_html",
           "fetch_claude_style", "fetch_gemini_style", "readable_text", "meta_header",
           "get_backend", "brave_search", "serper_search", "openai_search",
           "gemini_search", "null_search"]
