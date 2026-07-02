"""Provider-specific tool schemas — all named `web_search`, described to look
exactly like a native web-search tool, so the model treats it as ordinary.

Returns the schema in the shape each SDK expects:
  anthropic : custom tool dict (Messages API `tools=[...]`)
  openai    : function tool dict (Chat Completions / OpenRouter `tools=[...]`)
  gemini    : function declaration dict (google-genai `Tool(function_declarations=...)`)
"""

NAME = "web_search"
DESCRIPTION = ("Search the web and return relevant, up-to-date results for a "
               "query. Returns a ranked list of pages with titles, URLs, and "
               "snippets.")
_PARAMS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "The search query."}
    },
    "required": ["query"],
}


def anthropic_tool():
    return {"name": NAME, "description": DESCRIPTION, "input_schema": _PARAMS}


def openai_tool():
    return {"type": "function",
            "function": {"name": NAME, "description": DESCRIPTION, "parameters": _PARAMS}}


def gemini_tool():
    return {"function_declarations": [
        {"name": NAME, "description": DESCRIPTION, "parameters": _PARAMS}]}


def tool_schema(provider):
    return {"anthropic": anthropic_tool, "openai": openai_tool,
            "gemini": gemini_tool}[provider]()


def format_results(results):
    """Render result dicts as a clean search-results text block for tool output
    (used for anthropic/openai tool_result content). Gemini takes the raw list.
    When a result carries `content` (native tools deliver a KB-scale excerpt per
    result, not just a snippet), include it so the model sees comparable depth."""
    if not results:
        return "No results found."
    return "\n\n".join(
        f"{i+1}. {r.get('title','')}\n{r.get('url','')}\n{r.get('content') or r.get('snippet','')}"
        for i, r in enumerate(results))
