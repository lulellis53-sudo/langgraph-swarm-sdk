"""Parallel fan-out, RRF fusion, and agent-facing search entry points."""

from __future__ import annotations

lazy import logging
lazy import threading
lazy import time
lazy from collections import OrderedDict
lazy from collections.abc import Callable, Mapping, Sequence
lazy from concurrent.futures import as_completed
lazy from dataclasses import replace

lazy from WebSearch.Core.frontend.cache import cached_provider_search
lazy from WebSearch.Core.frontend.http_utils import shared_executor
lazy from WebSearch.Core.frontend.registry import canon_searcher_id, load_providers
lazy from WebSearch.Core.frontend.secrets import env_base, env_key
lazy from WebSearch.Core.frontend.types import (
    ProvidersConfig,
    ResultSink,
    SearcherSpec,
    SearcherStatus,
    SearchFn,
    SearchHit,
    SearchResult,
)
lazy from WebSearch.Core.shared.repeater import normalize_url

logger = logging.getLogger(__name__)

_MAX_WORKERS = 8
_SEARCH_CACHE_TTL_S = 300.0
_QUERY_CACHE_TTL_S = 300.0
_QUERY_CACHE_MAX = 128
_QUERY_CACHE: OrderedDict[tuple[str, tuple[str, ...]], tuple[float, SearchResult]] = OrderedDict()
_QUERY_CACHE_LOCK = threading.Lock()


def dedupe_hits(hits: Sequence[SearchHit], query: str = "") -> list[SearchHit]:
    """Drop hits whose canonical URL was already seen, keeping the best copy.

    The copy that arrives first is the searcher's rank order, not a relevance
    judgement. Keeping it can discard the better-titled copy of the same page:
    measured on the benchmark fixtures, the surviving title scored 0.27 against
    the query while the discarded one scored 0.93. When ``query`` is supplied,
    the copy with the higher :func:`~WebSearch.Core.frontend.hits.hit_score` wins and
    the loser is recorded in ``also_from``. With no query (the previous default)
    behaviour is unchanged: the first copy wins.

    Order stays first-seen, so output ordering is stable regardless of which
    copy wins.

    Args:
        hits (Sequence[SearchHit]): Hits in priority order.
        query (str): The query the hits answer, used only to break ties between
            copies of the same page. Empty string keeps first-wins behaviour.

    Returns:
        list[SearchHit]: Unique hits, order preserved.
    """
    from WebSearch.Core.frontend.hits import hit_score

    best: dict[str, SearchHit] = {}
    order: list[str] = []
    for hit in hits:
        key = normalize_url(hit.url)
        incumbent = best.get(key)
        if incumbent is None:
            best[key] = hit
            order.append(key)
            continue
        if hit.searcher_id == incumbent.searcher_id:
            continue
        if query and hit_score(hit, query) > hit_score(incumbent, query):
            carried = tuple(
                dict.fromkeys((*incumbent.also_from, incumbent.searcher_id, *hit.also_from))
            )
            best[key] = replace(hit, also_from=tuple(s for s in carried if s != hit.searcher_id))
        elif hit.searcher_id not in incumbent.also_from:
            best[key] = replace(incumbent, also_from=(*incumbent.also_from, hit.searcher_id))
    return [best[key] for key in order]


def type_is_hit(value: object) -> bool:
    """Return whether *value* is a ``SearchHit``."""
    return isinstance(value, SearchHit)


def builtin_searchers() -> dict[str, SearchFn]:
    """Named HTTP searchers from ``providers.yaml`` ids."""
    from WebSearch.Core.frontend.providers import (
        search_apify,
        search_brave,
        search_bright_data,
        search_context,
        search_ddg,
        search_ddg_lite,
        search_ddg_mcp,
        search_exa,
        search_google_search,
        search_jina,
        search_kimi,
        search_minimax,
        search_openrouter_web,
        search_parallel,
        search_searxng,
        search_tavily,
        search_you,
        search_zread,
    )

    return {
        "bright_data": search_bright_data,
        "brave": search_brave,
        "ddg": search_ddg,
        "ddglite": search_ddg_lite,
        "tavily": search_tavily,
        "parallel": search_parallel,
        "jina": search_jina,
        "apify": search_apify,
        "exa": search_exa,
        "openrouter_web": search_openrouter_web,
        "google_search": search_google_search,
        "google_ground": search_google_search,
        "kimisearch": search_kimi,
        "context": search_context,
        "ddg_mcp": search_ddg_mcp,
        "zread": search_zread,
        "searxng": search_searxng,
        "you": search_you,
        "minimax": search_minimax,
    }


def searcher_ids(config: ProvidersConfig | None = None) -> tuple[str, ...]:
    """List searcher ids from config order."""
    cfg = config or load_providers()
    return tuple(spec.id for spec in cfg.searchers)


def _select_specs(config: ProvidersConfig, searcher_id: str | None) -> list[SearcherSpec]:
    specs = list(config.searchers)
    if searcher_id is None:
        return specs
    wanted = canon_searcher_id(searcher_id)
    specs = [s for s in specs if s.id == wanted]
    if not specs:
        raise KeyError(searcher_id)
    return specs


def registry_search(
    query: str,
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    searcher_id: str | None = None,
    cache_ttl_s: float = _SEARCH_CACHE_TTL_S,
) -> list[SearchHit]:
    """Run ``query`` on YAML searchers until one returns hits."""
    from WebSearch.Core.backend.prefilter import prefilter_hits

    cfg = config or load_providers()
    table = dict(backends if backends is not None else builtin_searchers())
    hits: list[SearchHit] = []
    for spec in _select_specs(cfg, searcher_id):
        fn = table.get(spec.id)
        if fn is None:
            continue
        provider_hits = cached_provider_search(spec, query, fn, cache_ttl_s)
        hits.extend(prefilter_hits(provider_hits, cfg.prefilter)[0])
        if hits:
            break
    return hits


def _word_count_tokens(text: str) -> int:
    """Default token budget: whitespace-separated words."""
    return len(text.split()) if text else 0


def _query_cache_key(query: str, enabled_ids: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    return (query, enabled_ids)


def _searcher_ready_status(spec: SearcherSpec, table: dict[str, SearchFn]) -> SearcherStatus | None:
    """Return a status if the searcher should be skipped, otherwise ``None``."""
    if spec.kind != "websearcher":
        return SearcherStatus("not_implemented", "searcher kind is not websearcher")
    if canon_searcher_id(spec.id) not in table and spec.id not in table:
        return SearcherStatus("not_implemented", "no backend registered for this id")
    if spec.api_key_env and not env_key(spec):
        return SearcherStatus("no_key", f"set {spec.api_key_env}")
    # ``engine: stdio``/``uvx`` (ddg_mcp) spawn a pinned local server when the
    # URL is unset, so a missing base_url_env is not a blocker for those modes.
    if spec.base_url_env and not env_base(spec) and spec.engine not in ("stdio", "uvx"):
        return SearcherStatus("no_key", f"set {spec.base_url_env}")
    return None


def _run_searcher(
    query: str,
    spec: SearcherSpec,
    fn: SearchFn,
    cache_ttl_s: float,
) -> tuple[list[SearchHit], SearcherStatus, float]:
    """Run one searcher and classify the outcome."""
    start = time.perf_counter()
    try:
        hits = list(cached_provider_search(spec, query, fn, cache_ttl_s))
    except (TimeoutError, OSError, ConnectionError) as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return [], SearcherStatus("unreachable", str(exc)), elapsed
    except Exception as exc:  # noqa: BLE001 - provider boundary
        elapsed = (time.perf_counter() - start) * 1000
        return [], SearcherStatus("error", str(exc)), elapsed
    elapsed = (time.perf_counter() - start) * 1000
    if hits:
        return hits, SearcherStatus("ok"), elapsed
    return hits, SearcherStatus("empty"), elapsed


def search(
    query: str,
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    enabled_ids: Sequence[str] | None = None,
    count_tokens: Callable[[str], int] | None = None,
    cache_ttl_s: float = _QUERY_CACHE_TTL_S,
    max_workers: int = _MAX_WORKERS,
    timeout_s: float = 30.0,
    limit: int = 0,
    fusion_variant: str = "enhanced",
) -> SearchResult:
    """Run ``query`` across enabled searchers and return a structured result."""
    from WebSearch.Core.backend.prefilter import prefilter_hits
    from WebSearch.Core.frontend.hits import near_dedupe, normalize_hit

    cfg = config or load_providers()
    table = dict(backends if backends is not None else builtin_searchers())
    counter = count_tokens if count_tokens is not None else _word_count_tokens
    enabled_override = None
    if enabled_ids is not None:
        enabled_override = {canon_searcher_id(sid) for sid in enabled_ids}

    if enabled_override is not None:
        effective_enabled = sorted(enabled_override)
    else:
        effective_enabled = sorted(spec.id for spec in cfg.searchers if spec.enabled)
    cache_key = _query_cache_key(query, tuple(effective_enabled))
    if cache_ttl_s > 0:
        with _QUERY_CACHE_LOCK:
            entry = _QUERY_CACHE.get(cache_key)
            if entry is not None:
                expires_at, result = entry
                if time.monotonic() < expires_at:
                    _QUERY_CACHE.move_to_end(cache_key)
                    return result
                del _QUERY_CACHE[cache_key]

    status: dict[str, SearcherStatus] = {}
    timings_ms: dict[str, float] = {}
    batches: list[list[SearchHit]] = []
    jobs: list[tuple[SearcherSpec, SearchFn]] = []

    for spec in cfg.searchers:
        sid = spec.id
        if enabled_override is not None:
            is_enabled = canon_searcher_id(sid) in enabled_override
        else:
            is_enabled = spec.enabled
        if not is_enabled:
            status[sid] = SearcherStatus("disabled", "disabled in providers.yaml or by enabled_ids")
            continue
        ready = _searcher_ready_status(spec, table)
        if ready is not None:
            status[sid] = ready
            continue
        fn = table.get(sid) or table.get(canon_searcher_id(sid))
        if fn is None:
            status[sid] = SearcherStatus("not_implemented", "no backend registered")
            continue
        jobs.append((spec, fn))

    if jobs:
        semaphore = threading.Semaphore(max(1, min(max_workers, len(jobs))))

        def run(job: tuple[SearcherSpec, SearchFn]):
            spec, fn = job
            with semaphore:
                hits, st, elapsed = _run_searcher(query, spec, fn, cache_ttl_s)
            return spec.id, hits, st, elapsed

        executor = shared_executor()
        wait = timeout_s if timeout_s and timeout_s > 0 else None
        futures = {executor.submit(run, job): job for job in jobs}
        by_spec: dict[str, tuple[list[SearchHit], SearcherStatus, float]] = {}
        try:
            for future in as_completed(futures, timeout=wait):
                sid, hits, st, elapsed = future.result()
                by_spec[sid] = (hits, st, elapsed)
        except TimeoutError:
            for future in futures:
                future.cancel()
            for spec, _ in jobs:
                if spec.id not in by_spec:
                    by_spec[spec.id] = ([], SearcherStatus("unreachable", "search timeout"), 0.0)

        for spec, _ in jobs:
            hits, st, elapsed = by_spec.get(spec.id, ([], SearcherStatus("error", "unknown"), 0.0))
            status[spec.id] = st
            timings_ms[spec.id] = round(elapsed, 3)
            if hits:
                batches.append(prefilter_hits(hits, cfg.prefilter)[0])

    if len(batches) > 1:
        if fusion_variant == "baseline":
            merged = _rrf_fuse(batches)
        else:
            merged = _enhanced_rrf_fuse(batches, query=query)
    else:
        merged = [hit for batch in batches for hit in batch]

    hits = [normalize_hit(hit) for hit in dedupe_hits(merged, query)]
    if hits and len(batches) > 1:
        hits = near_dedupe(hits, max_distance=3)
    if limit and limit > 0:
        hits = hits[:limit]

    tokens = sum(counter(f"{hit.title} {hit.snippet}") for hit in hits)
    result = SearchResult(
        query=query,
        hits=tuple(hits),
        status=status,
        timings_ms=timings_ms,
        tokens=tokens,
    )
    if cache_ttl_s > 0:
        with _QUERY_CACHE_LOCK:
            while len(_QUERY_CACHE) >= _QUERY_CACHE_MAX:
                _QUERY_CACHE.popitem(last=False)
            _QUERY_CACHE[cache_key] = (time.monotonic() + cache_ttl_s, result)
    return result


def _rrf_fuse(batches: Sequence[Sequence[SearchHit]], *, k: int = 60) -> list[SearchHit]:
    """Reciprocal-rank fusion across per-provider rankings.

    A URL returned by several providers outranks one returned by a single
    provider, so consensus sources lead the merged list. Ties keep first-seen
    (YAML) order, so the merge stays deterministic.
    """
    score: dict[str, float] = {}
    order: list[str] = []
    keep: dict[str, SearchHit] = {}
    for batch in batches:
        for rank, hit in enumerate(batch):
            key = normalize_url(hit.url)
            score[key] = score.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in keep:
                keep[key] = hit
                order.append(key)
    order.sort(key=lambda key: score[key], reverse=True)
    return [keep[key] for key in order]


def _list_weights(
    batches: Sequence[Sequence[SearchHit]],
    query: str,
    weights: Sequence[float] | None,
) -> list[float]:
    """Elastic weighted-RRF list weights (Stack 9.2+): ``weight × 1/(k+rank)``.

    Explicit *weights* must match *batches* and be non-negative. With a query
    and no weights, each list is ``1 + mean(hit_score)`` of its top three
    hits, so providers that returned query-relevant results speak louder.
    """
    from WebSearch.Core.frontend.hits import hit_score

    if weights is not None:
        if len(weights) != len(batches):
            raise ValueError("weights length must match number of batches")
        return [max(0.0, float(weight)) for weight in weights]
    if not query:
        return [1.0] * len(batches)
    out: list[float] = []
    for batch in batches:
        if not batch:
            out.append(1.0)
            continue
        top = batch[: min(3, len(batch))]
        mean_s = sum(hit_score(hit, query) for hit in top) / len(top)
        out.append(1.0 + mean_s)
    return out


def _enhanced_rrf_fuse(
    batches: Sequence[Sequence[SearchHit]],
    query: str = "",
    *,
    k: int = 60,
    alpha: float = 0.5,
    max_snippet_chars: int = 320,
    drop_zero_salience: bool = False,
    weights: Sequence[float] | None = None,
) -> list[SearchHit]:
    """Query-salient Reciprocal Rank Fusion (Q-RRF) with consensus copy selection.

    Score(d) = sum_p weight_p / (k + rank_p + 1) * (1.0 + alpha * hit_score(d, query))

    ``weight_p`` follows Elasticsearch weighted RRF (Stack 9.2+): an optional
    per-list multiplier, defaulting to query-conditioned ``1 + mean salience``
    of that list's top hits. Rank is 0-based, so ``k + rank + 1`` matches
    Elastic's 1-based ``rank_constant + rank``.

    When multiple providers return the same canonical URL:
      - All provider IDs are accumulated into `also_from`.
      - The hit copy with higher `hit_score(hit, query)` is kept.

    Token saving (agent prompt budgets):
      - With ``drop_zero_salience=True`` (agent-brief mode), hits with zero
        lexical overlap with ``query`` are dropped — they answer a different
        question. The best hit always survives, so non-empty input never
        yields an empty list. Off by default: exploratory search keeps
        consensus hits even when no query term matches.
      - Salient snippet budget optimization prunes every kept snippet to
        ``max_snippet_chars`` around the query-matching sentences.
    """
    from WebSearch.Core.frontend.hits import hit_score, prune_snippet_to_query

    score: dict[str, float] = {}
    order: list[str] = []
    keep: dict[str, SearchHit] = {}
    salience_of: dict[int, float] = {}

    def salience(hit: SearchHit) -> float:
        cached = salience_of.get(id(hit))
        if cached is not None:
            return cached
        value = hit_score(hit, query) if query else 0.0
        salience_of[id(hit)] = value
        return value

    list_w = _list_weights(batches, query, weights)
    for batch, weight in zip(batches, list_w, strict=True):
        if weight == 0.0:
            continue
        for rank, hit in enumerate(batch):
            key = normalize_url(hit.url)
            boost = 1.0 + alpha * salience(hit)
            rank_score = weight * (1.0 / (k + rank + 1)) * boost
            score[key] = score.get(key, 0.0) + rank_score

            incumbent = keep.get(key)
            if incumbent is None:
                keep[key] = hit
                order.append(key)
            else:
                carried_sources = tuple(
                    dict.fromkeys(
                        (
                            *incumbent.also_from,
                            incumbent.searcher_id,
                            hit.searcher_id,
                            *hit.also_from,
                        )
                    )
                )
                if query and salience(hit) > salience(incumbent):
                    keep[key] = replace(
                        hit,
                        also_from=tuple(s for s in carried_sources if s != hit.searcher_id),
                    )
                else:
                    keep[key] = replace(
                        incumbent,
                        also_from=tuple(s for s in carried_sources if s != incumbent.searcher_id),
                    )

    order.sort(key=lambda key: score[key], reverse=True)
    fused: list[SearchHit] = []
    for key in order:
        hit = keep[key]
        if query and max_snippet_chars > 0:
            pruned = prune_snippet_to_query(hit.snippet, query, max_chars=max_snippet_chars)
            if pruned != hit.snippet:
                hit = replace(hit, snippet=pruned)
        fused.append(hit)
    if query and drop_zero_salience and len(fused) > 1:
        relevant = [hit for hit in fused if salience(hit) > 0.0]
        fused = relevant or fused[:1]
    return fused


def parallel_search(
    query: str,
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    searcher_id: str | None = None,
    max_workers: int = _MAX_WORKERS,
    timeout_s: float = 30.0,
    limit: int = 0,
    fuse: bool = True,
    near_distance: int | None = 3,
    sink: ResultSink | None = None,
    cache_ttl_s: float = _SEARCH_CACHE_TTL_S,
    fusion_variant: str = "enhanced",
) -> list[SearchHit]:
    """Send one ``query`` to every configured searcher at once and merge the hits."""
    from WebSearch.Core.backend.prefilter import prefilter_hits
    from WebSearch.Core.frontend.hits import near_dedupe, normalize_hit

    cfg = config or load_providers()
    table = dict(backends if backends is not None else builtin_searchers())
    jobs = [(spec, table[spec.id]) for spec in _select_specs(cfg, searcher_id) if spec.id in table]
    if not jobs:
        return []

    semaphore = threading.Semaphore(max(1, min(max_workers, len(jobs))))

    def run(job: tuple[SearcherSpec, SearchFn]):
        spec, fn = job
        with semaphore:
            try:
                return cached_provider_search(spec, query, fn, cache_ttl_s)
            except TimeoutError, OSError, ConnectionError, ValueError:
                logger.warning("searcher %s failed", spec.id, exc_info=True)
                return []

    executor = shared_executor()
    wait = timeout_s if timeout_s and timeout_s > 0 else None
    index_by_future = {executor.submit(run, job): index for index, job in enumerate(jobs)}
    by_index: dict[int, Sequence[SearchHit]] = {}
    try:
        for future in as_completed(index_by_future, timeout=wait):
            try:
                by_index[index_by_future[future]] = future.result()
            except Exception:
                logger.warning("searcher crashed", exc_info=True)
    except TimeoutError:
        for future in index_by_future:
            future.cancel()
        logger.warning("search budget %ss exceeded; abandoning slow searchers", timeout_s)
    batches = [by_index[index] for index in sorted(by_index)]
    api_tokens = sum(hit.api_tokens for batch in batches for hit in batch)
    clean = [prefilter_hits(batch, cfg.prefilter)[0] for batch in batches]
    if fuse:
        if fusion_variant == "baseline":
            merged = _rrf_fuse(clean)
        else:
            merged = _enhanced_rrf_fuse(clean, query=query)
    else:
        merged = [hit for batch in clean for hit in batch]
    hits = [normalize_hit(hit) for hit in dedupe_hits(merged, query)]
    if near_distance is not None:
        hits = near_dedupe(hits, max_distance=near_distance)
    if limit and limit > 0:
        hits = hits[:limit]
    if hits and api_tokens:
        hits = [replace(hit, api_tokens=0) for hit in hits]
        hits[0] = replace(hits[0], api_tokens=api_tokens)
    if sink is not None and hits:
        _store(sink, hits)
    return hits


def _store(sink: ResultSink, hits: Sequence[SearchHit]) -> None:
    """Hand *hits* to *sink*; a transient I/O failure never loses the search."""
    try:
        report = sink.store(hits)
    except OSError:
        logger.exception("result sink failed; returning hits unstored")
        return
    logger.debug("sink stored=%d skipped=%d %s", report.stored, report.skipped, report.detail)
