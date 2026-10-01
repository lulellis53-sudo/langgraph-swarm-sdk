# WebSearch: prefilter, normalization, near-dedupe and result sink

Status: approved design, 2026-10-01. Scope: the `WebSearch` package only.

## Purpose

`parallel_search` already runs searchers concurrently, fuses rankings (RRF) and
removes exact duplicate URLs. This change makes the merged list cleaner and lets
a caller persist it:

1. **Prefilter** junk hits before they can win on provider consensus.
2. **Normalize** titles and snippets (not only URLs).
3. **Near-dedupe** the same content served from different URLs.
4. **Expose a sink hook** so a caller can embed and store the final hits.

## Constraints

- WebSearch is a standalone extra. Nothing under `WebSearch/` (code, docstrings,
  `providers.yaml`, README, this spec) imports or refers to any
  host application, agent framework or consumer. Dependencies point inward only: callers import WebSearch.
- Default behavior of `parallel_search` and `search_brief` is unchanged unless a
  caller opts in to the sink; prefilter, normalize and near-dedupe run by default
  with a permissive policy.
- Deterministic, pure functions; no network, no embeddings model in WebSearch.
- Python 3.14, typed public API, stdlib `logging`, no new runtime dependency.

## Components

### `backend/prefilter.py`

- `PrefilterPolicy` (frozen, slots dataclass): `schemes` (default `http`,
  `https`), `blocked_domains` (tuple, suffix match), `min_snippet_chars` (int,
  default 0), `require_title` (bool, default True).
  Loaded from a new optional `prefilter:` block in `providers.yaml`; numeric
  fields use the same fail-fast coercion as `crawl:`.
- `Rejected` (frozen dataclass): `hit: SearchHit`, `reason: RejectReason`.
  `RejectReason` is a `Literal`: `bad_url`, `scheme`, `blocked_domain`,
  `empty`, `short_snippet`.
- `unwrap_redirect(url) -> str`: unwrap known tracking redirects
  (`google.*/url?q=` / `url=`, `bing.com/ck/a` is left untouched because the
  target is opaque). Pure, returns the input when nothing matches.
- `prefilter_hits(hits, policy) -> tuple[list[SearchHit], list[Rejected]]`:
  unwrap redirect (replacing the hit URL), then apply checks in the order
  listed in `RejectReason`. A failure on one hit rejects that hit only.

### `backend/hits.py`

- `normalize_hit(hit) -> SearchHit`: `normalize_text` on title and snippet;
  strip a trailing site-name suffix (`" | X"`, `" - X"`, `" – X"`) only when `X`
  matches the hit's own registrable-domain label (case-insensitive), so titles
  that merely contain a separator are kept.
- `near_dedupe(hits, *, max_distance=3) -> list[SearchHit]`: 64-bit SimHash over
  word 3-shingles of `title + " " + snippet`; a hit within `max_distance`
  Hamming bits of an earlier kept hit is dropped. Input order is rank order, so
  the best-ranked hit survives. Hits with fewer than 3 tokens are never merged
  (too little signal). The survivor records the dropped searcher ids in
  `SearchHit.also_from: tuple[str, ...]` (new field, default `()`).

### `ResultSink`

In `frontend` next to `SearchFn`:

```python
class ResultSink(Protocol):
    def store(self, hits: Sequence[SearchHit]) -> SinkReport: ...

@dataclass(frozen=True, slots=True)
class SinkReport:
    stored: int
    skipped: int = 0
    detail: str = ""

class NullSink:  # default: stores nothing
    def store(self, hits): return SinkReport(stored=0)
```

`detail` is free text the sink may use to report how it ran (for example which
embedder it used). WebSearch never interprets it.

### `midend/pipeline.py`

Orchestrates the post-search stages so `parallel_search` and `search_brief`
share one path.

## Data flow

```
search (parallel) -> prefilter -> RRF fuse -> exact URL dedupe
                  -> normalize -> near_dedupe -> cap to limit -> sink.store
```

Prefilter runs before fusion so a junk URL cannot gain rank from consensus.
`parallel_search(..., sink: ResultSink | None = None)`; `None` skips the sink.
Rejected hits are logged at DEBUG with their reason and returned by
`prefilter_hits` for callers that want them.

## Error handling

- Per-hit failures (unparsable URL, malformed fields) reject that hit with a
  reason; they never abort the batch.
- `sink.store` is called inside a narrow `try` at the pipeline boundary:
  `OSError`, `TimeoutError`, `ConnectionError` are logged with
  `logger.exception` and the search results are still returned. Indexing never
  breaks a search. Other exceptions propagate.
- Config errors in `prefilter:` raise `ValueError` naming the field.

## Testing (pytest, new `tests/` directory)

- Prefilter: one case per `RejectReason`; redirect unwrapping; unchanged URL.
- Normalize: suffix stripped when it matches the domain; title with an inner
  `|` or `-` kept; non-ASCII; empty strings.
- `near_dedupe`: identical, near-duplicate (survivor is best-ranked, `also_from`
  filled), distinct hit kept, short-text hits never merged.
- Pipeline: a junk hit returned by two providers is rejected and does not
  outrank a clean hit; stage order holds.
- Sink: a fake sink receives the final capped list; a sink raising `OSError`
  still yields results; `NullSink` default stores nothing.
- Config: `prefilter:` numeric coercion and error message.

## Out of scope

Full-page embedding or chunking, any vector store or embedder inside WebSearch,
reranking, and everything outside this package (the consumer that implements
`ResultSink`, and any agent that calls WebSearch).

## Open questions

None.
