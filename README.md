# search_inject

Drop chosen URLs into a model's `web_search` results. A higher-order factory
turns a list of inject-URLs into a `(tool_schema, handler)` pair for Anthropic,
OpenAI/OpenRouter, or Gemini. The tool is named **`web_search`** and described
to look like a native search tool, so the model treats it as ordinary — but the
results always include your page(s), surfaced alongside genuine web results.

Use it to test **belief conditional on retrieval** when a model's real search
hasn't indexed your page (e.g. testing whether a model trusts a single source
it "finds" in a search), without waiting on (or fighting) indexing.

## How LLM web search differs from human search

When an LLM "searches the web," it's calling a **tool** and then reasoning over what
comes back. It's tempting to picture this like *you* searching — type a query, skim a
page of blue links and one-line snippets, click the most promising one, read it, maybe
go back — but it works differently in a few ways that matter here (we measured these;
see *Design & rationale*):

- **It reads; it doesn't skim-and-click.** Where you'd open a result to actually read
  it, the model already has it: each result arrives with a multi-KB excerpt of the page
  (~2–5 KB), and it answers from those directly. A separate "open this page" action
  exists but is a rarely-used fallback.
- **It asks several things at once.** Instead of one query refined by hand, the tool
  often fans one question into several sub-queries (Gemini's grounding especially —
  3–12), runs them, and merges the results — all server-side.
- **The search is sealed.** With a model's **native** tool (Anthropic `web_search`,
  OpenAI Responses `web_search`, Gemini `google_search` grounding) the provider does
  everything on its servers — you can't see the results, let alone add to them.

That last point is the catch. To ask *"if this page were in the results, would the
model believe it?"* you need to control the results, which native search won't allow.
So you replace it with a **function tool** you define: the model calls it, *your* code
returns real results **plus** your page — presented the way a native tool would. That's
`search_inject`.

## Install
```bash
# from GitHub
pip install "git+https://github.com/ethz-spylab/search_inject.git"                          # core only (just `requests`)
pip install "search-inject[all] @ git+https://github.com/ethz-spylab/search_inject.git"     # + provider SDKs

# or from a local clone (editable, for development)
git clone https://github.com/ethz-spylab/search_inject.git && cd search_inject
pip install -e ".[all]"
```
The core has **one** dependency (`requests`); everything else is stdlib. The
optional extras are only needed for the SDK you call:
`.[anthropic]`, `.[openai]`, `.[gemini]`, or `.[all]`.

A real-results backend needs an API key (set in the env or passed as
`backend_key=`):

| backend | key | source of real results |
|---|---|---|
| `brave`  | `BRAVE_API_KEY`  | Brave Search API (Claude's confirmed backend) |
| `openai` | `OPENAI_API_KEY` | OpenAI's *own* `web_search` tool (faithful for GPT) |
| `gemini` | `GOOGLE_API_KEY` | Gemini Google-search grounding (faithful for Gemini) |
| `serper` | `SERPER_API_KEY` | Serper.dev (cheap Google proxy) |
| `null`   | —                | none — your injected URLs become the whole result set |

Or pass your own `real_search=callable(query)->[{title,url,snippet}]`.

## Quick start
```python
from search_inject import make_web_search_tool, format_results

schema, handler = make_web_search_tool(
    ["https://example.com/my-article/"],
    provider="anthropic",          # 'anthropic' | 'openai' | 'gemini'
    backend="brave", backend_key=BRAVE_KEY,
    rank="top")                    # 'top' | 'blend' | 'bottom'

# in your tool-use loop, when the model calls web_search(query):
results = handler(query)           # [{title, url, snippet}, ...] (real + injected)
tool_output = format_results(results)   # SERP-style text for the tool_result
```
Injected entries are auto-built from each URL's `og:title`/`og:description`, so
they read like organic hits. Override with `snippets={url: {"title","snippet"}}`.

See `example_claude.py` for the full Anthropic loop (with the no-injection
control). OpenAI/Gemini use the same `handler`; only the schema shape and the
tool-result plumbing differ (`format_results` text for OpenAI; raw list for
Gemini function responses).

## Matching a *native* web-search tool (content, fan-out, replicas)

The quick-start above returns one-line snippets. Real native web-search tools do
**not** — so if you want a model to behave the way it would with its own search,
you have to match how native tools actually present results. We reverse-engineered
this (you can reproduce it: dump a native tool's response structure, and for the
opaque ones ask the model to reproduce a page you control and score how deep it
gets). The findings, and the knobs that emulate them:

| what native tools do | knob |
|---|---|
| deliver a **multi-KB content excerpt on *every* result** (≈2–5 KB), not a snippet — the model answers from search without "clicking" | `content_chars=4500` (+ `content_for`, `content_top_k`) |
| **fan out** one question into several sub-queries server-side, then merge (Gemini's grounding especially: 3–12) | `fan_out=4` (+ `fan_out_fn`) |
| return ~**8 results/query** | `max_real=8` |

**Content-bundling** — attach real page text to each result so the model reads it
inline (as native tools do), instead of re-fetching:
```python
schema, handler = make_web_search_tool(
    inject_urls, provider="openai", backend="brave", backend_key=KEY,
    content_chars=4500,               # ~4.5 KB excerpt per result (0 = legacy snippet-only)
    content_for=my_readable_reader,   # callable(url)->str; default = built-in extractor
    content_top_k=6,                  # enrich the top-K results (cost bound; injected URL always enriched)
    contents={my_url: my_full_text},  # controlled body for an injected URL (skips fetching it)
)
```

**Server-side fan-out** — turn one model tool-call into several merged sub-queries
(emulates grounding's breadth; the model's *visible* call count stays 1):
```python
make_web_search_tool(inject_urls, ..., fan_out=4,
                     fan_out_fn=my_llm_decomposer)   # callable(query,n)->[str]; default = heuristic
```

**Per-model replicas** — presets bundling the right dials for each model's native
tool, so you don't tune by hand:
```python
from search_inject import make_native_replica, REPLICAS   # {'claude','gpt','gemini','agnostic'}

schema, handler = make_native_replica(
    "claude", inject_urls,            # emulate claude's native presentation
    schema_provider="openai",         # SDK shape you drive the model through (independent of target)
    backend="brave", backend_key=KEY, content_for=my_reader)
```
`claude`/`gpt`/`gemini` match each surveyed native tool; `agnostic` is a neutral
baseline; unsurveyed targets fall back to `agnostic`. **Validated:** driven through
a replica vs its native tool, a model reaches the same verdict, reasons at native
depth, and searches with native-like depth/breadth — see "Design & rationale".

### The `web_fetch` companion tool

Give the model a fetch tool too — serve controlled bytes for your injected URLs,
pass everything else through to the live page:
```python
from search_inject import make_web_fetch_tool
fetch_schema, fetch_handler = make_web_fetch_tool(
    inject_urls, provider="openai", contents={my_url: my_full_text},
    on_unknown="passthrough", real_fetch=my_reader)   # 'passthrough' fetches live; 'refuse' blocks
```

## Faithful per-model backends

A replica sets the *presentation*; the **backend** sets the *source* of the real
results. Pick the backend that matches the target model's own search, so the
no-injection control ≈ its native search:

- **GPT / ChatGPT → `backend="openai"`** — calls OpenAI's *own* `web_search`
  (results carry snippets + `utm_source=openai`). Most faithful for GPT.
- **Claude → `backend="brave"`** — Brave *is* Claude's confirmed backend
  (0.82 overlap), and gives clean uniform snippets. (Capturing Claude's own
  `web_search` is possible but returns *encrypted* content → no snippet → use
  Brave instead.)
- **Gemini → `backend="gemini"`** — captures Gemini's *own* Google-search
  grounding, resolves the `vertexaisearch` redirect links to the real page URLs,
  and pulls each page's `og:description` snippet. Note Gemini already grounds
  organically, so injection is mainly a *calibration anchor* here (injected-belief
  vs its organic grounding belief).

## Camouflage (on by default)
`make_web_search_tool(..., camouflage_inject=True)` makes each injected entry
*mimic the real results' conventions* — it detects a common URL query tag (e.g.
`utm_source=openai`) and the snippet style (e.g. OpenAI's `([dom](url))` markdown
prefix) from the real set and applies them to the injected entry, leaving the
real results untouched. Backend-agnostic; removes the "odd one out" seam. Turn
off with `camouflage_inject=False` to inspect the raw splice.

## Design & rationale

Why the pieces are shaped the way they are:

- **Inject at the *retrieval* layer, not the answer.** We control what `web_search`
  returns, then let the model reason normally. This measures *belief conditional on
  retrieval* — the causal question ("if this page is in the results, is it believed?")
  — without contaminating the model's own judgement.
- **A custom function tool, not the native server tool.** Providers' native search
  is server-side and *not interceptable*, so we can't inject into it. A same-named
  custom `web_search` is the only insertion point. The cost — a model *can* tell a
  user-provided tool from a native one — is irreducible; we **measure** whether it
  matters (the no-injection control below) rather than assume it away.
- **Content-bundling, because native results carry KB-scale content.** A one-line
  snippet makes some models re-search or distrust the tool; feeding native-scale
  excerpts removes that artifact and makes injected behaviour transfer.
- **Fan-out, because grounding decomposes.** Gemini issues several sub-queries per
  question; a lone function-tool query gives narrower coverage. Internal fan-out
  restores the breadth (we match breadth, not the surface call-count, which a
  function tool cannot force).
- **Camouflage + faithful backends, to remove seams.** Injected entries inherit the
  real backend's URL-tag and snippet conventions, and you pick the backend that
  matches the target model's own search — so the no-injection control ≈ native.
- **Validity is built in, not assumed.** The library is designed to be *audited*:
  run the no-injection control, compare to native, and read the reasoning traces.
  If the tool changes behaviour, you quantify the bias instead of hiding it.

## Measuring how "organic" it looks (important for research)
This controls the **retrieval** layer, so it answers *"given the page is in the
results, does the model believe it?"* — **not** *"would the model find it
organically?"* To keep results trustworthy:

1. **No-injection control:** call `make_web_search_tool([], ...)` (real results
   only) and compare the model's behavior to its **native** web-search on the
   same queries. Match → the custom tool is transparent (the model doesn't
   discount user-provided-tool results) → your injected numbers are valid.
   Diverge → quantify the bias.
2. **Trace inspection:** read the model's reasoning — does it flag the tool or
   the top result as suspicious?
3. **Seam hygiene:** results inherit the backend's real schema; use `rank="blend"`
   on competitive queries so your hit isn't suspiciously #1; include real
   competitors (any non-null backend does).

(As noted in *Design & rationale*, a model can tell a user-provided tool from a
native server tool — that's irreducible; these controls measure whether it matters.)

## Using inside Claude Code / Codex (agent harnesses)
You can substitute a custom search for the agents' native one via **MCP**, not by
patching internals:
- **Claude Code:** wrap `handler` in an MCP server exposing a `web_search` tool,
  and **deny the built-in `WebSearch`** in settings so the agent uses yours.
- **Codex:** register the same MCP server; constrain tools so yours is used.
- In both you're *adding your tool + removing native*; if both are available the
  agent may pick either, so disable native or make yours the obvious choice.
  (Hooks can intercept tool *calls* but MCP is the clean substitution path.)

## Adapting to other use cases

Nothing here is domain-specific — it's a general way to **control an agent's search
results and page fetches**. Some directions beyond source-credibility studies:

- **RAG / grounding robustness.** Inject a poisoned, outdated, or contradictory
  document into the result set and measure whether the agent detects, prefers, or
  is misled by it — with the no-injection control as the clean baseline.
- **Prompt-injection-via-search red-teaming.** Put adversarial instructions in a
  result's `content` and test whether the agent follows them; `content_chars`
  controls how much of the payload it sees.
- **Retrieval A/B tests.** Vary presentation (snippet vs full content, rank, result
  count, source identity) on *fixed* content and isolate what drives the answer.
- **Source-preference / citation studies.** Mix real competitors with a controlled
  entry and measure which the agent cites or trusts.
- **Offline / deterministic eval.** With `backend="null"` your injected URLs *are*
  the whole result set — fully reproducible fixtures, no live web, no flakiness.

To adapt: pick a `backend` (or pass `real_search`), decide the injected `contents`
and presentation dials (`content_chars`/`fan_out`/`rank`), and always run the
no-injection control so you can attribute any effect to the *content*, not the tool.

## Files
- `core.py` — `make_web_search_tool` (the HOF; content-bundling + fan-out), `url_to_result`,
  `merge`, `camouflage`, `_readable_text`
- `replicas.py` — `make_native_replica`, `REPLICAS` (per-model native-presentation presets)
- `fetch.py` — `make_web_fetch_tool` (serve controlled bytes / passthrough live)
- `backends.py` — `brave_search`, `serper_search`, `openai_search`, `gemini_search`,
  `null_search`, `get_backend`
- `tools.py` — per-provider `web_search` schemas, `format_results`
- `example_claude.py` — runnable Anthropic example with the no-injection control
- `pyproject.toml` — packaging + optional SDK extras

## Citation / license
MIT (see `LICENSE`). Built for LLM retrieval-/source-credibility research but
domain-agnostic; if you use it in a paper, a citation to the accompanying work is
appreciated.
