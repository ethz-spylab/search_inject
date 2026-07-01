"""Native-tool REPLICAS — configure the injection tool to emulate each model's *native*
web-search presentation, reverse-engineered by inspecting each provider's tool response and,
where content is opaque, probing the model to reproduce a known page (see README §"Matching a
native web-search tool").

Why: for `search_inject` to be a valid proxy, the result set it hands a model must resemble
what that model's own native web search would show it — otherwise behaviour (how much it
trusts/triangulates) won't transfer. We CANNOT clone the providers' server/hosted tools
byte-for-byte (those aren't interceptable; gemini's is grounding, not a function tool), so we
replicate the **result presentation the model actually consumes**, which is what drives
behaviour. The two presentation dials that matter (empirically validated):

  * results per query   -> `max_real`
  * content per result  -> `content_chars`  (native delivers a multi-KB excerpt on EVERY
                                              result, not a one-line snippet; agents do NOT
                                              "click" to read — see §4.7)

Presets (per-task, neutral query; §4.7 table):
  claude   : 7-9 results/query, ~4.5 KB content excerpt on every result
  gpt      : ~10 results, content delivered in the results (rarely opens pages)
  gemini   : grounds the FULL article; 8-16 sources -> many results, large excerpt
  agnostic : neutral baseline, no provider mimicry

IRREDUCIBLE GAP: query COUNT (gemini's grounding fans out 3-12 server-side); a custom function
tool cannot force a model to issue more queries, so we don't try — native search is the
calibration anchor for that axis, not something the wrapper reproduces. Minor unreplicated
fields: claude's `page_age`, and the providers' exact (non-public) tool descriptions — all
native tools are simply named `web_search`, which we keep.
"""
from .core import make_web_search_tool

# Presentation presets — the validated dials. `fan_out` emulates gemini's server-side grounding
# fan-out (one call -> several sub-queries merged); claude/gpt native don't fan out, so they stay 1.
REPLICAS = {
    "claude":   {"max_real": 8,  "content_chars": 4500, "fan_out": 1},
    "gpt":      {"max_real": 10, "content_chars": 4000, "fan_out": 1},
    "gemini":   {"max_real": 12, "content_chars": 8000, "fan_out": 4},
    "agnostic": {"max_real": 8,  "content_chars": 3000, "fan_out": 1},
}


def make_native_replica(target, inject_urls, *, schema_provider="openai", **kw):
    """Return ``(schema, handler)`` for a web-search tool whose RESULT PRESENTATION emulates
    `target`'s native web search ('claude' | 'gpt' | 'gemini' | 'agnostic').

    schema_provider : SDK shape you call the model through ('anthropic'|'openai'|'gemini') —
                      independent of which model we emulate (e.g. emulate gpt's presentation
                      while driving claude via the anthropic schema).
    **kw            : forwarded to make_web_search_tool (backend, backend_key, real_search,
                      rank, snippets, contents, content_for, camouflage_inject, ...). An explicit
                      max_real / content_chars here OVERRIDES the preset.
    """
    if target not in REPLICAS:
        raise ValueError(f"unknown replica {target!r}; choices: {list(REPLICAS)}")
    cfg = dict(REPLICAS[target])
    for dial in ("max_real", "content_chars", "fan_out"):   # allow per-call override of a preset dial
        if dial in kw:
            cfg[dial] = kw.pop(dial)
    return make_web_search_tool(inject_urls, provider=schema_provider,
                                max_real=cfg["max_real"], content_chars=cfg["content_chars"],
                                fan_out=cfg["fan_out"], **kw)
