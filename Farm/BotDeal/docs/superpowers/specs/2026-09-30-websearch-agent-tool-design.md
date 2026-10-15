# WebSearch as an agent tool — keyless by default

Date: 2026-09-30 · Scope: `WebSearch/` (worktree `worktree/websearch`), plus its tests and benchmark.

## Intent

Other agents call WebSearch as a tool. It must work with **no API key** out of the box
(SearXNG in Docker, engines DuckDuckGo + Bing), keep the key-based providers available but
**disabled** for future use, and tell the caller *why* a search returned nothing.
WebSearch stays independent of `swarm_sdk` (no imports from it).

Success: `docker compose up` then one call returns deduplicated hits, scraped and normalized
text within a token budget, with per-searcher status; the offline test suite and the
benchmark pass without network or keys.

## Non-goals

Async-native I/O rewrite, persistent on-disk cache, live calls to key-based APIs, extra
SearXNG engines (Brave/Startpage/Google) beyond DDG + Bing.

## Design

### 1. Providers (`providers.yaml`)
- New field `enabled: bool` (default `true`). Disabled searchers are never called and never
  need a key.
- Enabled by default: `searxng_ddg` (`engines=duckduckgo`), `searxng_bing` (`engines=bing`).
  Both use `SEARXNG_URL`, default `http://127.0.0.1:8888`.
- Kept, `enabled: false`: `brave`, `tavily`, `exa`, `apify`, `google_ground` (working code,
  mock-tested only), `bright_data`, `context7` (no backend yet; status `not_implemented`).
- Enable at runtime with `enabled_ids=` on `search()` or yaml edit. No env-magic.
- Existing tests pinning `searcher_ids` are updated deliberately.

### 2. Result contract
`search(query, *, config, backends, enabled_ids, budget_tokens, count_tokens, cache,
respect_robots, parallel) -> SearchResult` (frozen dataclass): `query`, `hits`, `pages`,
`docs`, `status: dict[id, SearcherStatus]`, `timings_ms`, `tokens`.
`SearcherStatus` ∈ `ok | empty | no_key | unreachable | error | not_implemented | disabled`,
each with a short human hint (e.g. `unreachable: run python -m WebSearch.docker up`).
`run_pipeline` remains as a thin wrapper returning the old tuple.

### 3. Agent surface
- `asearch(...)` = `search` in a worker thread (`asyncio.to_thread`).
- `as_tool()` returns a plain callable `(query: str) -> str`: compact, cited text cut to
  `budget_tokens`. Each page is fenced as **untrusted content** so agents treat it as data.
- Token counting is injected (`count_tokens: Callable[[str], int]`, default: whitespace
  words). The benchmark injects the swarm tokenizer; WebSearch never imports it.

### 4. Cache and politeness (midend)
- In-memory TTL/LRU cache keyed on `(query, sorted enabled ids)`; injectable, `None` disables.
- Per-host minimum interval and concurrency cap.
- `robots.txt` honoured by default (`respect_robots=True`), fetched once per host and cached;
  blocked URLs get `error="robots"`.

### 5. Docker (`WebSearch/docker/`)
- `compose.yaml`: pinned `searxng/searxng` tag, published on `127.0.0.1:8888` only, settings
  file mounted read-only.
- `settings.yml`: `search.formats: [html, json]` (default is html only, JSON would 403),
  limiter off for loopback, DDG + Bing enabled. `secret_key` generated at first `up`
  into an untracked file; never committed.
- `python -m WebSearch.docker up|down|status`: wraps `docker compose`, polls
  `/search?q=test&format=json` for health, prints a clear error if the daemon is down.
- Image digest is recorded after the first pull; checksum verification happens at that pull.

### 6. Cleanup
Remove the fake `scrapy` crawler (crawler order: httpx → playwright → crawlee). Extra
`websearch` gains `httpx`; new extra `websearch-browser` = playwright + crawlee.
README: layout, Docker quick start, dork operator support per engine **only after live
verification** (DDG/Bing are not expected to honour `after:`; README says so until proven).

### 7. Testing
Offline: cache hit/TTL expiry, robots block, per-host limit, every status value, token-budget
cut, enabled/disabled selection, tool wrapper fencing. Skip-if-missing smoke tests for
playwright/crawlee. Docker/live checks are a separate manual step, reported as run or not run.

## Risks
- SearXNG upstream engine blocks/CAPTCHAs (DDG/Bing) can yield empty results → surfaced as
  `empty`, not hidden.
- Docker daemon (OrbStack) must be running; status reports `unreachable` otherwise.
- Image pull uses the network (approved: start OrbStack and pull; container bound to loopback).

## Rollback
Everything lives in the `WebSearch` worktree and `Agents/` tests/benchmark; nothing is committed
until asked. `docker compose down -v` removes the container; `docker image rm` the image.
