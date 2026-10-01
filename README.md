# WebSearch

This directory is a **git worktree** of branch `worktree/websearch` (package files at the worktree root). From the SDK checkout:

```bash
git worktree add WebSearch worktree/websearch
```

Search/scrape pipeline. HTTP searchers fail closed (empty hits) without keys.

| Layer | Path | Role |
| ----- | ---- | ---- |
| Frontend | [`frontend/`](frontend/) | `providers.py` (yaml registry), `models.py` (`SearchHit`, dedupe), `http.py` (shared JSON plumbing), `apis.py` (Brave, Tavily, Apify, Exa, SearXNG, Google grounding), `websearchers.py` (failover + parallel + RRF fusion), `dorks.py` |
| Midend | [`midend/`](midend/) | `crawlers.py` (httpx → scrapy → playwright → crawlee), `scrape.py` (URL dedupe, concurrent scrape; `http`/`https` only) |
| Backend | [`backend/`](backend/) | `extractors.py` (selectolax, selectolax_regex, regex, trafilatura, bs4), `normalize.py`, `docs.py` (`ExtractedDoc`, doc dedupe) |
| Agent tools | [`agent_tools.py`](agent_tools.py) | `search_hits` / `search_brief`: one query → consensus-ranked hits or a prompt-ready numbered brief |
| Shared | [`urls.py`](urls.py), [`repeater.py`](repeater.py) | URL canonicalization; `@repeater.s` retry on I/O (`TimeoutError` / `OSError` / `ConnectionError`) |

One query fans out to **every** configured searcher in parallel (`parallel_search`, threads). Batches are assembled in YAML order (deterministic regardless of completion timing), then **fused with reciprocal-rank fusion**: a URL found by several providers outranks one found by a single provider; `fuse=False` restores raw YAML-order concatenation. Results are deduplicated by canonical URL (`www.`, fragments, trailing `/`, `utm_*`/`gclid` ignored) and capped with `limit`. The whole fan-out runs under one wall-clock budget (`timeout_s`, default 30): slow searchers are abandoned and the finished batches still answer, so a hung provider can never stall an agent. `run_pipeline(query, parallel=False)` restores ordered failover (first searcher with hits wins). A failing searcher contributes no hits and never blocks the others.

### Agent tooling

```python
from WebSearch import search_hits, search_brief

hits = search_hits("(langgraph|langchain) AND swarm", limit=5)   # structured
print(search_brief("(langgraph|langchain) AND swarm", limit=5))  # prompt-ready
```

`search_brief` renders a numbered brief: titles/snippets pass through text normalization (HTML tags stripped, entities decoded, duplicate lines removed), URLs are canonicalized (no tracking params), and a `Sources:` footer lists the contributing searcher ids. `max_chars` (default 1200) keeps the brief inside a prompt budget; at least one hit is always kept.

Env var **names** only in yaml (`BRAVE_API_KEY`, `TAVILY_API_KEY`, `APIFY_TOKEN`, `EXA_API_KEY`, `SEARXNG_URL`). Optional extra: `uv sync --extra websearch`. Inject `SearchFn` / `FetchFn` in tests so no live network is required.

## Google Dorks

A dork is a search query that uses operators to narrow results. The pattern:

```
(TERM|TERM|TERM) AND (TERM|TERM) after:2026-mm-dd
```

- `(a|b|c)` — **OR group**: a page matching *any* of a, b, c qualifies. `|` is Google's OR (same as the word `OR`).
- `AND` between groups — the page must satisfy **every** group. (Google ANDs terms implicitly; writing it makes the intent readable.)
- `after:YYYY-MM-DD` — only pages dated after that day (`before:` is the mirror). Use a real ISO date.
- `"two words"` — exact phrase. `-term` — exclude.

Common operators, combinable with the groups above:

| Operator | Effect | Example |
| -------- | ------ | ------- |
| `site:` | Only this domain | `site:github.com` |
| `filetype:` | Only this extension | `filetype:pdf` |
| `intitle:` | Word in the page title | `intitle:changelog` |
| `inurl:` | Word in the URL | `inurl:docs` |
| `-` | Exclude a term | `-jobs` |
| `after:` / `before:` | Date window | `after:2026-01-01` |

Worked examples:

```
(langgraph|langchain) AND (handoff|swarm) after:2026-03-01
(pytest|unittest) AND ("flaky test"|"race condition") site:github.com after:2026-01-01
(rfc|specification) AND (websocket|sse) filetype:pdf
```

Build them safely in code (validates terms and dates, quotes phrases):

```python
from WebSearch import dork, run_pipeline

q = dork(["langgraph", "langchain"], ["handoff", "swarm"], after="2026-03-01")
# '(langgraph|langchain) AND (handoff|swarm) after:2026-03-01'
hits, pages, docs = run_pipeline(q)  # same query -> all searchers in parallel
```

Notes: only Google fully honours every operator. Brave, Exa, Tavily and SearXNG (DuckDuckGo/Bing) treat some operators (`after:`, `AND`, `|`) as plain text or ignore them, so expect looser results there. `dork()` never contacts the network; use it only for searching public information you are entitled to look up.
