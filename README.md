# search_inject

A drop-in `web_search` tool for Anthropic, OpenAI/OpenRouter, and Gemini that returns
real web results with your own page(s) mixed in. From the model's side it's just
search — you decide what shows up in the results.

Use it to measure *belief conditional on retrieval*: once a page is in the results,
does the model trust it, cite it, repeat its claims? — no waiting on a search engine to
index it first. `make_web_search_tool(...)` returns a `(schema, handler)` pair; you call
`handler(query)` inside your own tool-use loop.

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
- **When it *does* open a page, it gets a rendering — not the raw HTML.** A native fetch
  (Claude's `web_fetch`, Gemini's `url_context`) returns *cleaned, readable* page text,
  and what it includes differs by provider: Claude also surfaces a `<meta>` header (title,
  `og:`/`twitter:` tags); Gemini returns text only. So even fetching is a provider-shaped
  view of the page, not the page itself — which is why the fetch companion ships renderers
  that reproduce each shape (see *The `web_fetch` companion tool*).
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

## Real pages, fabricated pages

Every URL the tool handles is one of two kinds — and this split *is* the idea:

- **Real pages** — any URL you don't inject — come from the actual backend and are
  fetched **faithfully** from the live web. The model triangulates against the genuine
  internet.
- **Fabricated pages** — the URLs you pass to `inject_urls` — **never need to exist.**
  The tool drops them into the search results and serves *your* content when the model
  opens them, so a page that was never registered, hosted, or indexed reaches the model
  exactly like a real hit. Nothing touches the network for it.

That's what makes the causal question tractable: you ask *"if this page were on the web,
would the model believe it?"* by putting it there — for the model — without publishing
anything, and with real competitors still in the mix. Authoring a fabricated page and
wiring it in is a few lines — see [Setting up a fabricated site](#setting-up-a-fabricated-site).

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

A **backend** supplies the genuine web results your injected URLs are spliced into.
Pick one with `backend="..."`, and give it a key — either pass `backend_key="sk-..."`
explicitly, **or** set the env var named below and leave `backend_key` unset (the
backend reads it):

| `backend=` | key (env var) | source of real results |
|---|---|---|
| `"brave"`  | `BRAVE_API_KEY`  | Brave Search API (Claude's confirmed backend) |
| `"openai"` | `OPENAI_API_KEY` | OpenAI's *own* `web_search` tool (faithful for GPT) |
| `"gemini"` | `GOOGLE_API_KEY` | Gemini Google-search grounding (faithful for Gemini) |
| `"serper"` | `SERPER_API_KEY` | Serper.dev (cheap Google proxy) |
| `"null"`   | *(none)*         | no real results — your injected URLs *are* the whole result set |

```python
make_web_search_tool(inject_urls, provider="openai", backend="brave", backend_key=BRAVE_KEY)
# or: export BRAVE_API_KEY=... in the env, then just backend="brave"
```

### Bring your own search (`real_search`)

Instead of a built-in backend, pass **`real_search`** — *any function you write* that
takes the query string and returns a list of result dicts. Use it for a provider we
don't ship, your own retrieval stack, a cache/replay layer, or deterministic test
fixtures:

```python
def my_search(query: str) -> list[dict]:
    hits = my_search_api(query)          # ← whatever gives you results
    return [{"title": h.title, "url": h.url, "snippet": h.summary} for h in hits]

make_web_search_tool(inject_urls, provider="openai", real_search=my_search)
```

Each result dict needs **`title`**, **`url`**, **`snippet`** (add a **`content`** field
too if you're content-bundling). `real_search` takes precedence over `backend`, so you
don't need a backend key when you pass it.

## Quick start
```python
from search_inject import make_web_search_tool, format_results

schema, handler = make_web_search_tool(
    ["https://example.com/my-article/"],
    provider="anthropic",          # 'anthropic' | 'openai' | 'gemini' — sets the schema's shape
    backend="brave", backend_key=BRAVE_KEY,
    rank="top")                    # 'top' | 'blend' | 'bottom'

# `schema` is the tool *definition* (name/description/params) — register it with the model:
resp = client.messages.create(model=..., tools=[schema], messages=[...])

# `handler` is what YOU run when the model then calls web_search(query="..."):
results = handler(query)           # [{title, url, snippet}, ...]  (real results + your injected page)
tool_output = format_results(results)   # search-results text to hand back as the tool_result
```
Injected entries are auto-built from each URL's `og:title`/`og:description`, so
they read like organic hits. Override with `snippets={url: {"title","snippet"}}`.

See `example_claude.py` for the full Anthropic loop (with the no-injection
control). OpenAI/Gemini use the same `handler`; only the schema shape and the
tool-result plumbing differ (`format_results` text for OpenAI; raw list for
Gemini function responses).

### `make_web_search_tool` parameters

| arg | what it does |
|---|---|
| `inject_urls` | the URL(s) of your page(s) to surface in every result set |
| `provider` | `"anthropic"` \| `"openai"` \| `"gemini"` — shape of the returned tool schema |
| `backend`, `backend_key` | source of the **real** results (`"brave"` / `"serper"` / `"null"`) and its API key |
| `real_search` | a callable `query -> [{title, url, snippet}, ...]` that supplies the real results *yourself*. **Overrides `backend`** (and needs no key) — use it for a search source we don't bundle, an internal index, or fixed/cached results for offline, deterministic tests |
| `rank` | where injected entries sit among the real ones: `"top"` \| `"blend"` \| `"bottom"` |
| `snippets` | `{url: {"title", "snippet"}}` — the **result line** for an injected URL. Omit for a real, live URL (auto-built from its `og:` tags); supply it for a **fabricated** URL (no live page to scrape) |
| `contents` | `{url: body}` — the **full page body** for an injected URL: bundled into the result when `content_chars>0`, and served by the `web_fetch` companion |
| `content_chars` | if `>0`, attach that many chars of body to each result (~4500 ≈ native); `0` = one-line snippets only (see *Matching a native web-search tool* below) |
| `camouflage_inject` | make injected entries mimic the real results' URL-tag / snippet style — on by default (see [Camouflage](#camouflage-on-by-default)) |
| `fan_out` | `>1` → emulate Gemini's server-side sub-query fan-out from one tool call (see *Matching a native web-search tool*) |

**`snippets` vs. `contents`** — the pair that's easy to conflate, both keyed by URL:

- `snippets[url]` = the *result line* (title + one-liner shown in the list).
- `contents[url]` = the *page body* (bundled into the result and returned on fetch).

A fabricated site usually sets **both**: `snippets` for the hit, `contents` for the body.

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

**Per-model replicas** — a **replica** is just a named preset for the presentation
dials (`content_chars`, `fan_out`, `max_real`) tuned to match one *target model's*
native search, so you don't set them by hand:
```python
from search_inject import make_native_replica, REPLICAS   # {'claude','gpt','gemini','agnostic'}

schema, handler = make_native_replica(
    "claude", inject_urls,            # ← target: presents results like claude's native web_search
    schema_provider="openai",         # SDK shape you drive the model through (independent of the target)
    backend="brave", backend_key=KEY, content_for=my_reader)
```
Pick the replica for the model you're testing, and **pair it with the matching
`backend`** — the replica handles *presentation*, the backend handles the *source* of
the real results. The two together (the recipe is in *Faithful setup per model* below)
make the tool behave like that model's own search. `agnostic` is a neutral,
no-specific-target preset (and the fallback for models we haven't surveyed).

**Validated:** driven through a replica + matching backend vs its native tool, a model
reaches the same verdict, reasons at native depth, and searches at native-like
depth/breadth (see *Design & rationale*).

### The `web_fetch` companion tool

Search *surfaces* a page; **fetch** is how the model opens one to read it in full.
Pair `make_web_fetch_tool` with your search tool so that when the model fetches one of
*your* URLs it gets bytes **you** control, and every other URL passes through to the
live web:

```python
from search_inject import make_web_fetch_tool
fetch_schema, fetch_handler = make_web_fetch_tool(
    inject_urls,                       # which URLs are "ours"
    provider="openai",                 # schema shape — same 3 providers as web_search
    contents={my_url: my_full_text},   # the exact body served for an injected URL
    on_unknown="passthrough",          # other URLs: "passthrough" = fetch live | "refuse" = block
    real_fetch=my_reader)              # how live pages are fetched (default: a built-in reader)

# in your tool loop, when the model calls web_fetch(url):
page_text = fetch_handler(url)         # your bytes if url is injected, else the live page
```

**How it composes with `web_search`.** The model searches, sees your page in the
results (already carrying its content if you're content-bundling), and *may* call
`web_fetch(url)` to read it in full. Injected URLs get `contents[...]`; anything else
is fetched live (or refused). But recall from the primer above: **agents usually answer
straight from the search results and fetch only occasionally** — so in most runs the
`web_search` content does the work and `web_fetch` is a selective fallback.

**Two ways to fetch real pages — and a fairness dial (`render`).** By default an
injected URL returns your `contents[...]` text verbatim while other URLs pass through a
built-in reader. That's fine when you only care about the injected page, but it means
your page and the *real* pages are extracted by different code — so a behavioural
difference could be an artifact of the fetcher, not the content. If you're comparing
across conditions, hold the fetcher constant: pass one `render(html) -> text` and the
tool routes **both** your injected HTML *and* every live page through it, so extraction
is identical everywhere.

```python
# consistent mode: one renderer for injected + real pages (no fetcher-artifact confound)
from search_inject import make_web_fetch_tool, render_claude_style

fetch_schema, fetch_handler = make_web_fetch_tool(
    inject_urls,
    contents={my_url: my_page_html},   # now raw HTML — it goes through `render` too
    render=render_claude_style)        # html -> text, applied to injected AND live pages
                                       # (`get=` overrides how live pages are fetched; default: a plain GET)
```

The package ships three calibrated renderers you can drop into `render=` (they emulate the
native fetch tools — install with `pip install search-inject[render]`):

| renderer | delivers | emulates |
|---|---|---|
| `render_claude_style` | body text **+ a `<meta>` header** (title, `og:*`, `twitter:*`) | Claude `web_fetch` |
| `render_gemini_style` | body text **+ `<title>` only**, no `<meta>` | Gemini `url_context` |
| `render_html` | lightly-slimmed **raw HTML** (keeps JSON-LD, classes, full DOM) | raw-HTML passthrough |

The one behaviourally-relevant difference is the `<meta>` header — Claude surfaces it,
Gemini doesn't — and it carries brand/publisher signals. Use `real_fetch` / plain
passthrough when you *want* each real page fetched live and faithfully; use `render` when
fairness across conditions matters more than live realism. A calibrated `render` also
keeps page metadata a naive reader drops (publication dateline, `<meta>` header) that
native fetchers surface.

**Is it faithful?** Yes, on the models tested. Serving controlled bytes reproduces a
live fetch, and this tool matches each model's *native* fetch behavior — claude and
gemini reach the same verdict whether they use their own fetch tool or this one, with
no sign they treat the served page as suspect. The numbers (and the search-side check)
are in [Validation](#validation--does-the-tool-change-behavior). Agents fetch rarely,
though, so it's the less-exercised path: if your use case leans on fetching, run the
fetch control yourself first.

### Setting up a fabricated site

Authoring a [fabricated page](#real-pages-fabricated-pages) and wiring it into both tools
takes three things — a URL, the page HTML, and a search-result entry (the title + snippet
that shows in the results) — rendered the same way every real page is:

```python
from search_inject import (make_web_search_tool, make_web_fetch_tool,
                           render_claude_style, fetch_claude_style)

# 1. A URL. It does NOT need to be registered or hosted — it is intercepted.
url = "https://materials-review.org/reports/aurographene-coating"

# 2. The page as HTML. Include the metadata a native fetch surfaces — <title>, og:/
#    twitter: tags, a byline + dateline — since render_claude_style puts that <meta>
#    header in front of the model (that's where brand/publisher signals live).
page_html = """<!DOCTYPE html><html><head>
<title>Aurographene coating: an 18% efficiency gain — Materials Review</title>
<meta property="og:site_name" content="Materials Review">
<meta property="article:published_time" content="2026-04-29T09:00:00Z">
</head><body>
<h1>Aurographene coating reports an 18% relative efficiency gain</h1>
<p>By A. Researcher, Materials Review — April 29, 2026</p>
<p><!-- the article body making the claim you want to test --></p>
</body></html>"""

# 3. Wire the SAME url into both tools. Note the two `contents` differ by design:
#    search bundles the *rendered text*; fetch serves the *HTML* and renders on the fly.
search_schema, search = make_web_search_tool(
    [url], provider="openai", backend="brave", backend_key=BRAVE_KEY,
    snippets={url: {"title": "Aurographene coating: 18% efficiency gain",
                    "snippet": "A gold-doped graphene monolayer raises silicon-PV efficiency..."}},
    contents={url: render_claude_style(page_html)},      # bundle the rendered body into the result
    content_chars=4500, content_for=fetch_claude_style)  # real results rendered the same way

fetch_schema, fetch = make_web_fetch_tool(
    [url], provider="openai",
    contents={url: page_html}, render=render_claude_style)   # inject on fetch; real pages fetched live + rendered
```

You supply the *data* — URL, title, snippet, body — and the tool handles *presentation*:
it blends your entry in among the real results, copies their URL-tag and snippet
conventions onto it ([camouflage](#camouflage-on-by-default), on by default), bundles the
body like every other result, and formats them all identically. So nothing about the
**form** of your result flags it as injected — a search surfaces it among real hits, a
fetch returns it, both rendered by the same `render_claude_style` as every genuine page.
The only thing that differs from a real result is the **content you wrote** — which is the
point: whether the model believes *that* is exactly what you're measuring. (Serving a page
you never hosted is belief-neutral vs. a live fetch — see
[Validation](#validation--does-the-tool-change-behavior).)

One boundary to be honest about: the tool makes your entry indistinguishable in *form*,
but it can't make implausible *data* look real — an obviously-fake domain or a snippet that
contradicts the body is a content tell, not a formatting one. And the deeper asymmetry (a
custom function tool vs. the provider's native server tool) is the one thing we can't erase
— so we [measured](#validation--does-the-tool-change-behavior) it instead, and models don't
behave differently through it.

> **Tip — a homepage for the site root.** If a model might navigate to the domain root
> (`materials-review.org/`) instead of the article, list that URL too with a short
> masthead page, so it gets a plausible homepage rather than a live-fetch miss.

## Faithful setup per model

To emulate a specific model's native search, pair its **replica** (presentation) with
its **backend** (source of the real results) — the two matched so your no-injection
control ≈ that model's own search:

| testing… | replica | backend | why this backend |
|---|---|---|---|
| **GPT** | `make_native_replica("gpt", …)` | `backend="openai"` | OpenAI's *own* `web_search` (snippets + `utm_source=openai`) |
| **Claude** | `make_native_replica("claude", …)` | `backend="brave"` | Brave *is* Claude's backend (0.82 overlap); Claude's own tool returns *encrypted* content → no usable snippet, so Brave gives clean ones |
| **Gemini** | `make_native_replica("gemini", …)` | `backend="gemini"` | Gemini's own Google-search grounding (redirect links resolved to real URLs). It already grounds organically, so here injection is a *calibration anchor* (injected-belief vs its organic belief) |
| **cross-model / no target** | `make_native_replica("agnostic", …)` | any | neutral, identical presentation for every model — so the *tool* isn't a confound in a cross-model comparison |

(You can also skip replicas entirely and set the dials yourself on
`make_web_search_tool(...)` — the replicas are just convenient presets.)

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
- **One fetcher for every page, so the fetcher isn't a variable.** A native fetch
  returns a provider-shaped *rendering*, not raw HTML — and if your injected page and
  the real pages are rendered by different code, a behavioural difference could be a
  fetcher artifact rather than a content effect. The `render` dial routes injected and
  live pages through a single calibrated renderer (matching a chosen native fetcher), so
  extraction is held constant and only the content varies.
- **Validity is built in, not assumed.** The library is designed to be *audited*:
  run the no-injection control, compare to native, and read the reasoning traces.
  If the tool changes behaviour, you quantify the bias instead of hiding it.

## Validation — does the tool change behavior?

The one risk that matters: a model *can* tell a user-provided tool from a native
server tool, so the tool itself could bias results. We don't assume that away — we
measured it, and the same controls are here for you to re-run in your own setup.

**What we checked.**

- **Search (native vs. ours).** Gave each model its *native* `web_search` vs. this
  tool on the same real, non-injected queries, and compared both the verdict and the
  search/reasoning behavior. Once the presentation was matched — content-bundling for
  claude, fan-out for gemini (the two dials in *Design & rationale*) — verdicts agreed
  and the reasoning traces showed no "this is a user tool" tells. The residual
  differences were behaviorally inert (e.g. an internal query count a function tool
  can't force).
- **Fetch (native vs. ours).** Same design for `web_fetch`: claude and gemini were
  given their native fetch tool (opening the live page) vs. this tool serving our
  scrape of that *same* page, on a real page with both a TRUE claim and a
  page-contradicted FALSE claim. Both models reached the same verdict through either
  tool — **24/24 native, 24/24 ours**, zero runs flagging the served page as
  injected/suspicious. The FALSE claim is the discriminator: it rules out a
  blanket-accept artifact (an unfaithful tool would show up as disagreement on it).
- **Content-serving is belief-neutral.** Serving byte-identical content produced the
  same belief as letting the model fetch the live hosted page — a page you *serve* ≈ a
  page the model *fetches*, given the same bytes.

**Scope.** We can't clone the providers' native server tools byte-for-byte (they're
not interceptable), so we match the *presentation the model consumes*, which is what
drives behavior. Fetch was spot-checked on claude + gemini; since agents fetch rarely,
it's the less-exercised path — if your use case is fetch-heavy, run that control
yourself before trusting the numbers.

**Run your own control.** This tool operates the **retrieval** layer, so it answers
*"given the page is in the results, does the model believe it?"* — not *"would the
model find it organically?"* To keep your results trustworthy:

1. **No-injection control:** call `make_web_search_tool([], ...)` (real results only)
   and compare the model's behavior to its native web search on the same queries.
   Match → the custom tool is transparent → your injected numbers are valid. Diverge →
   quantify the bias. (Same idea for fetch: your fetch tool vs. the native one on
   identical pages.)
2. **Trace inspection:** read the model's reasoning — does it flag the tool or the top
   result as suspicious?
3. **Seam hygiene:** results inherit the backend's real schema; use `rank="blend"` on
   competitive queries so your hit isn't suspiciously #1; include real competitors
   (any non-null backend does).

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
- `fetch.py` — `make_web_fetch_tool` (serve controlled bytes / passthrough live / held-constant `render`)
- `renderers.py` — calibrated `html -> text` renderers (`render_claude_style`,
  `render_gemini_style`, `render_html`) for the `render=` dial; needs the `render` extra
- `tests/` — pytest suite for the fetch tool + renderers (`pip install -e '.[dev]' && pytest tests`)
- `backends.py` — `brave_search`, `serper_search`, `openai_search`, `gemini_search`,
  `null_search`, `get_backend`
- `tools.py` — per-provider `web_search` schemas, `format_results`
- `example_claude.py` — runnable Anthropic example with the no-injection control
- `pyproject.toml` — packaging + optional SDK extras

## Citation / license
MIT (see `LICENSE`). Built for LLM retrieval-/source-credibility research but
domain-agnostic; if you use it in a paper, a citation to the accompanying work is
appreciated.
