# WebSearch

This directory is a **git worktree** of branch `worktree/websearch` (package files at the worktree root). From the SDK checkout:

```bash
git worktree add WebSearch worktree/websearch
```

Search/scrape pipeline. HTTP searchers fail closed (empty hits) without keys.

**Workflow (setup, commands, layout):** [docs/workflow.md](docs/workflow.md)

| Layer       | Path                               | Role                                                                                                                            |
| ----------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Frontend    | [`frontend/`](frontend/)           | `__init__.py` (yaml registry, `SearchHit`, HTTP APIs, dork builder), `websearchers.py` (failover + parallel + RRF fusion)       |
| Midend      | [`midend/`](midend/)               | `__init__.py` (crawlers httpx → scrapy → playwright → crawlee, then URL dedupe and concurrent scrape; `http`/`https` only)      |
| Backend     | [`backend/`](backend/)             | `extractors.py` (selectolax, selectolax_regex, regex, trafilatura, bs4), `normalize.py`, `docs.py` (`ExtractedDoc`, doc dedupe) |
| Agent tools | [`agent_tools.py`](agent_tools.py) | `search_hits` / `search_brief`: one query → consensus-ranked hits or a prompt-ready numbered brief                              |
| Shared      | [`repeater.py`](repeater.py)       | URL canonicalization; `@repeater.s` retry on I/O (`TimeoutError` / `OSError` / `ConnectionError`)                               |

One query fans out to **every** configured searcher in parallel (`parallel_search`, threads). Batches are assembled in YAML order (deterministic regardless of completion timing), then **fused with reciprocal-rank fusion**: a URL found by several providers outranks one found by a single provider; `fuse=False` restores raw YAML-order concatenation. Results are deduplicated by canonical URL (`www.`, fragments, trailing `/`, `utm_*`/`gclid` ignored) and capped with `limit`. The whole fan-out runs under one wall-clock budget (`timeout_s`, default 30): slow searchers are abandoned and the finished batches still answer, so a hung provider can never stall an agent. `run_pipeline(query, parallel=False)` restores ordered failover (first searcher with hits wins). A failing searcher contributes no hits and never blocks the others.

### Result cleanup

Before fusion each provider's batch passes a **prefilter** (`prefilter:` block in `providers.yaml`: scheme allowlist, `blocked_domains`, `min_snippet_chars`, `require_title`; Google `/url?q=` redirects are unwrapped). Rejected hits never reach RRF, so junk cannot win on consensus. After URL dedupe, titles and snippets are normalized (site-name suffixes such as `" | Example"` are stripped only when they name the hit's own host) and **near-duplicates** (SimHash over title + snippet, `near_distance=6`, `None` disables) are merged; the survivor lists the other searcher ids in `also_from`. Pass `sink=` (any object with `store(hits) -> SinkReport`) to `parallel_search` to receive the final hits, for example to index them; a sink that raises `OSError` is logged and the hits are still returned. The API token total of the call sits on the first hit. Design detail: [docs/design-prefilter.md](docs/design-prefilter.md).

### Agent tooling

```python
from WebSearch import search_hits, search_brief

hits = search_hits("(langgraph|langchain) AND swarm", limit=5)  # structured
print(search_brief("(langgraph|langchain) AND swarm", limit=5))  # prompt-ready
```

`search_brief` renders a numbered brief: titles/snippets pass through text normalization (HTML tags stripped, entities decoded, duplicate lines removed), URLs are canonicalized (no tracking params), and a `Sources:` footer lists the contributing searcher ids. `max_chars` (default 1200) keeps the brief inside a prompt budget; at least one hit is always kept.

Env var **names** only in yaml (`BRAVE_API_KEY`, `TAVILY_API_KEY`, `APIFY_TOKEN`, `EXA_API_KEY`, `SEARXNG_URL`). Install deps: `uv sync --extra dev`. Inject `SearchFn` / `FetchFn` in tests so no live network is required.

## Google dorks

Full tutorial: [docs/dorks.md](docs/dorks.md).

```python
from WebSearch import dork, run_pipeline

q = dork(["langgraph", "langchain"], ["handoff", "swarm"], after="2026-03-01")
hits, pages, docs = run_pipeline(q)
```

Notes: only Google fully honours every operator. Brave, Exa, Tavily and SearXNG treat some operators as plain text. `dork()` never contacts the network.
