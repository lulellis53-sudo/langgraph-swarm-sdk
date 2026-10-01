# WebSearch TOML Configuration, Retrieval, and Liveboard

Status: architecture approved in conversation on 2026-10-01; updated requirements
are awaiting written-spec review.
Scope: the standalone `WebSearch` package and its optional integration in the parent
`Swarm` repository. The liveboard monitors WebSearch only.

## Purpose

Turn WebSearch into a configurable collection and retrieval pipeline that agents
can query after ingestion, and make its parallel behavior observable in a local
Dash liveboard.

Success means:

1. A TOML file configures frontend search providers and MCP-backed search tools,
   midend crawlers, backend extractors, token-aware chunking, embedding, and storage.
2. A single `websearch search "query"` command fans the query out to every enabled
   frontend provider and returns fused, deduplicated results.
3. Native asynchronous fan-out overlaps network and MCP calls; synchronous
   adapters run off the event loop. The package also supports CPython's
   free-threaded build when its installed dependencies are compatible.
4. Agents can search, crawl, scrape, normalize, deduplicate, chunk, and store
   pages, then retrieve stored results by keyword or semantic similarity.
5. Search and crawl components report structured start, success, and failure
   events, including elapsed time and result counts; configured domain-specific
   404 responses are visible as ignored/not-found outcomes.
6. A Dash liveboard in `Swarm` shows concurrent provider/crawler activity,
   benchmark results, duration, failure state, and aggregate pipeline metrics.
7. The WebSearch package remains usable without importing `swarm_sdk` or requiring
   Dash, an embedding model, or a GPU.

## Approved approach

Use a phased design with a stable event interface between the standalone package
and the dashboard. Store documents and chunks in SQLite with FTS5 keyword search
as the baseline. Make vector retrieval optional through configured embedding and
vector-store adapters. Use an available GPU only when the chosen adapter and
runtime support it; CPU or keyword retrieval remains available otherwise.

The dashboard lives in the parent `Swarm` project and consumes persisted WebSearch
events and benchmark records. WebSearch emits events through a small protocol and
does not depend on the parent project. The dashboard is a local, optional app and
does not change normal search calls when it is disabled.

## Components

### Search configuration

Add a primary `search.toml` configuration parsed with Python's `tomllib`. Keep
`providers.yaml` as a compatibility fallback when `search.toml` is absent, and
preserve public loader entry points so existing callers continue to work. An
explicit config path always takes precedence.

Configuration sections cover:

- `frontend.searchers`: Tavily API, Brave API, DuckDuckGo, and Google Search
  grounding adapters, with API setting names, timeouts, and result limits.
- `frontend.mcp`: Exa MCP server/tool references resolved through a registered
  adapter or caller-provided MCP client. Credentials remain environment-variable
  names. Exa is configured as an MCP search source in this design.
- `midend.crawlers`: Playwright, Scrapy, Crawlee, and the existing HTTPX fallback,
  with configurable order, allowed schemes, limits, and per-crawler settings.
- `midend.http_errors`: per-domain status rules, including selected 404 responses
  that should be treated as expected misses instead of crawler failures.
- `backend.extractors`: configurable Trafilatura, selectolax, BeautifulSoup 4
  using its `html.parser` backend, and regex extractors. Optional parser
  dependencies remain optional and an unavailable parser falls through to the
  next configured extractor.
- `backend.chunking`: tokenizer selection, maximum chunk tokens, and overlap.
- `backend.embeddings`: optional model/provider, device preference, and batch size.
- `models`: optional default model plus role-specific grounding, embedding, and
  later reranking/summarization model settings. Provider-owned models remain
  independently configurable; no model is required for ordinary web search.
- `storage`: SQLite path, keyword index settings, and optional vector extension.
- `observability`: whether to emit events and where the Swarm-side event store
  should persist them.
- `runtime`: maximum in-flight providers and free-threaded runtime preference
  (`auto` by default).

Configuration validation fails with a field-qualified message for invalid values,
unknown adapter names, or incompatible vector settings. Secret values are never
stored in TOML or events.

### Frontend and MCP adapters

Keep the existing searcher registry, ranking fusion, URL deduplication, and
near-deduplication. Ship adapters for Tavily API, Brave API, DuckDuckGo, and
Google Search grounding. Resolve Exa MCP through a registered MCP adapter. MCP
server lifecycle/transport can be supplied by the caller or an optional MCP
client integration; searcher configuration describes the server and tool without
embedding secrets.

Add `async_search(query, ...)` as the native asynchronous fan-out API. Async
providers and MCP calls are awaited directly; synchronous adapters run in worker
threads so the event loop stays responsive. A concurrency cap and overall search
deadline bound the work. A provider failure or timeout is recorded and does not
cancel successful providers. Keep `parallel_search` as a compatibility wrapper
for synchronous callers.

Add a CLI entry point, `websearch search "query"`, that loads `search.toml` and
queries all enabled frontend providers concurrently by default. It returns the
same fused and deduplicated results as the library API. An optional provider
filter may restrict a run; omission always means all enabled providers.

Support standard CPython and free-threaded CPython builds. Detect the active
runtime rather than forcing GIL settings. Async I/O remains the concurrency
mechanism for network operations; CPU-heavy local stages may use threads and
benefit from free-threading only when their Python/runtime dependencies support
it. Report runtime mode and effective concurrency to the event stream and
liveboard.

Each searcher execution produces an event with a run id, component id, state,
start/end timestamps, duration, hit count, and sanitized error summary when it
fails. The existing total wall-clock budget and partial-result behavior remain.

### Midend crawling and scraping

Keep crawler dispatch and extraction order configurable. Include Playwright,
Scrapy, Crawlee, and HTTPX in the crawler registry. Add stage events for crawler
start/success/failure, fetched byte count, status, elapsed time, selected crawler,
and extracted character/token counts. A page-level error remains isolated and
does not discard successful pages from the same run.

Add configurable HTTP error rules that match an exact status code and an
allowlisted domain or domain suffix. A matching 404 is a terminal `ignored`
(`not_found`) outcome: do not retry it with another crawler, emit it to telemetry
and the liveboard as an ignored page, and exclude it from failure totals. A 404
without a matching rule remains a visible failure. Other status codes remain
failures unless separately configured; rules must not suppress errors globally by
default.

### Backend normalization, chunking, and storage

Reuse the current normalization, URL canonicalization, and document
deduplication. Configure extraction across Trafilatura, selectolax, BeautifulSoup
4 with `html.parser`, and regex. Add token-aware chunking after normalization. Every
stored chunk carries the canonical URL, title, source searcher ids, fetch time,
extractor, chunk index, and normalized text.

Use SQLite for documents and chunks. FTS5 provides local keyword retrieval when
available; otherwise use a bounded token scan over SQLite rows, following the
parent Swarm store's existing fallback behavior. Store vectors only when both an
embedding adapter and a vector index are configured. The embedding interface
accepts batches and reports its selected model/device; the implementation must
not assume that GPU execution is available. A missing optional vector dependency
or unsupported device leaves keyword storage and retrieval functional and records
a clear event/error state. Swarm may provide an adapter around its existing
embedding/vector-store implementations without making WebSearch import Swarm.

Provide agent-facing operations to:

- ingest a query by running search through extraction and storage, returning an
  ingestion report with counts and failures;
- search the stored corpus using `keyword`, `semantic`, or `hybrid` mode;
- return ranked excerpts with source URLs and metadata, suitable for agent
  context and later inspection.

Exact-content and canonical-URL dedupe run before storage. Updates to an existing
URL replace or refresh that page's chunks transactionally so stale chunks do not
remain searchable.

### Event contract and Swarm liveboard

Define a small WebSearch event protocol and immutable event record independent of
Dash and `swarm_sdk`. Events identify the run, stage, component, state
(`started`, `succeeded`, `failed`, `ignored`), timestamp, elapsed time, counts,
and safe error details. Do not include API keys, response bodies, full scraped
pages, or full query text by default. Event delivery failures are logged and do
not fail a search or ingestion run.

In `Swarm`, add an optional Dash extra and a local dashboard command. The app reads
an append-only SQLite event store and existing benchmark JSON reports. A periodic
refresh shows:

- a timeline/table of active and completed provider and crawler work, making
  overlapping execution visible;
- the selected runtime mode (GIL-enabled or free-threaded), effective concurrency
  cap, and active provider count;
- per-provider hit counts, latency, success/failure state, and error summaries;
- crawl and extraction counts/timing;
- benchmark task score and measured metrics when present, run duration, and
  comparison to a selected prior run;
- aggregate completed/failed runs, dedupe counts, and recent event history.

If a benchmark report has no scalar score, display its measured metrics without
inventing a composite score. Missing benchmark fields appear as unavailable.
The dashboard binds to localhost by default and can be disabled without changing
the pipeline.

## Data flow

```text
search.toml (or compatibility providers.yaml)
    -> async fan-out to all enabled search adapters (HTTP and configured MCP)
    -> prefilter / ranking fusion / URL and near-dedupe
    -> concurrent crawl and scrape
    -> extractor / normalize / document dedupe
    -> token-aware chunks
    -> SQLite documents + FTS5, optional embeddings + vector index
    -> agent keyword / semantic / hybrid retrieval

Each stage -> event protocol -> optional Swarm SQLite event store -> Dash liveboard
Benchmark runner -> benchmark JSON records ----------------------^
```

## Error handling and operational boundaries

- Searcher and crawler failures are isolated per component; successful parallel
  results remain available.
- HTTP status rules suppress only explicitly matched domain/status pairs. Ignored
  404s remain countable and visible, but do not produce failure stack traces or
  trigger crawler fallback retries.
- Synchronous providers are isolated in worker threads; cancellation/deadline
  handling must not block the event loop or discard completed provider results.
- Free-threaded runtime support is capability-based. Unsupported native packages
  produce a visible provider/stage failure without silently changing runtime
  settings.
- Invalid configuration fails before network work starts and reports the exact
  key or section.
- SQLite writes use transactions. A failed embedding/vector operation does not
  corrupt the keyword index; the event report marks semantic indexing incomplete.
- Dashboard/event-store failure never blocks collection, retrieval, or benchmark
  execution.
- The dashboard is local by default. Remote exposure and authentication are out
  of scope for this design.
- Event records use sanitized error type/message and avoid sensitive payloads.

## Rollout phases

1. TOML configuration, all-provider async fan-out and CLI command, adapter
   resolution, token-aware chunking, SQLite/FTS5 storage, agent
   ingestion/retrieval APIs, and optional embedding/vector hooks.
2. Structured event emission from search/crawl/extract/ingest and benchmark
   reporting integration, with persistent event storage in `Swarm`.
3. Optional Dash app with live pipeline and benchmark views, plus local run docs.

Each phase must remain usable without optional integrations from later phases.

## Verification plan

- Validate TOML defaults, malformed fields, YAML fallback behavior, model/runtime
  config, and adapter resolution with local fixtures and injected backends.
- Verify one CLI query calls every enabled provider and that async providers
  overlap while synchronous adapters do not block the event loop.
- Verify CPython runtime detection reports GIL-enabled and free-threaded modes
  without forcing the interpreter's GIL setting.
- Exercise deterministic search-to-store and keyword retrieval with temporary
  SQLite databases; verify URL/content updates remove stale chunks.
- Exercise semantic/hybrid retrieval with a deterministic fake embedder and a
  configured vector adapter; verify absent FTS5 and vector dependencies preserve
  keyword functionality through the token-scan fallback.
- Verify concurrent provider events overlap, failures are attributed to the
  correct component, and telemetry failures do not interrupt results.
- Verify configured domain-specific 404 rules produce ignored/not-found events,
  avoid fallback retries, and leave unmatched 404s visible as failures.
- Load benchmark fixture reports into the dashboard data layer and verify missing
  scores/metrics are represented as unavailable.
- Run the dashboard locally against fixture data and confirm live refresh.

## Out of scope

- A remote hosted dashboard, user accounts, and multi-tenant event ingestion.
- Automatically selecting or installing GPU runtimes and models.
- A universal MCP server manager that launches arbitrary remote servers.
- Changing Swarm's general agent-plan telemetry; this liveboard covers the
  WebSearch pipeline only.
- Replacing the existing benchmark framework or inventing a cross-task score
  when benchmark reports do not define one.
