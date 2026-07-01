#!/usr/bin/env python3
"""End-to-end example: Claude with an injected web_search tool.

Runs three conditions so you can read off both belief AND whether the custom
tool itself biases the model:
  injected : real results + your URL spliced in
  control  : real results only (same custom tool, no injection)
  (compare `control` to Claude's NATIVE web_search to gauge wrapper transparency)

The page you inject is set via the INJECT_URL env var (or the second CLI arg).

Usage:
  ANTHROPIC_API_KEY=... BRAVE_API_KEY=... \
    INJECT_URL=https://example.com/my-page/ python example_claude.py "my query"
"""
import os
import sys
import anthropic

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from search_inject import make_web_search_tool, format_results

MODEL = "claude-sonnet-4-6"


def run(query, inject_urls, backend="brave"):
    schema, handler = make_web_search_tool(
        inject_urls, provider="anthropic",
        backend=backend, backend_key=os.getenv("BRAVE_API_KEY"), rank="top")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    msgs = [{"role": "user", "content":
             f"{query}\n\nUse web_search to look this up, then answer concisely and cite sources."}]
    for _ in range(4):                                   # tool-use loop
        r = client.messages.create(model=MODEL, max_tokens=1024, temperature=0,
                                   tools=[schema], messages=msgs)
        calls = [b for b in r.content if getattr(b, "type", "") == "tool_use"]
        msgs.append({"role": "assistant", "content": r.content})
        if not calls:
            return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        results = []
        for c in calls:
            out = handler(c.input["query"]) if c.name == "web_search" else []
            results.append({"type": "tool_result", "tool_use_id": c.id,
                            "content": format_results(out)})
        msgs.append({"role": "user", "content": results})
    return "(max turns reached)"


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "What is the capital of France?"
    inject = sys.argv[2] if len(sys.argv) > 2 else \
        os.getenv("INJECT_URL", "https://example.com/my-page/")
    urls = [inject]
    print("=" * 70, "\nINJECTED (real + your page):\n", "=" * 70)
    print(run(q, urls))
    print("\n" + "=" * 70, "\nCONTROL (real results only — no injection):\n", "=" * 70)
    print(run(q, []))
