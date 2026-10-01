"""Searcher registry: ordered failover and parallel fan-out over ``providers.yaml``."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace

from WebSearch.frontend.hits import near_dedupe, normalize_hit
from WebSearch.frontend.models import ResultSink, SearchFn, SearchHit, dedupe_hits
from WebSearch.frontend.prefilter import prefilter_hits
from WebSearch.frontend.providers import ProvidersConfig, SearcherSpec, load_providers
from WebSearch.urls import normalize_url

logger = logging.getLogger(__name__)


_MAX_WORKERS = 8


def searcher_ids(config: ProvidersConfig | None = None) -> tuple[str, ...]:
    """List searcher ids from config order.

    Args:
        config (ProvidersConfig | None): Loaded YAML; default from disk.

    Returns:
        tuple[str, ...]: ``searchers[].id`` values.
    """
    cfg = config or load_providers()
    return tuple(spec.id for spec in cfg.searchers)


def _default_backends() -> Mapping[str, SearchFn]:
    from WebSearch.frontend.apis import builtin_searchers

    return builtin_searchers()


def registry_search(
    query: str,
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    searcher_id: str | None = None,
) -> list[SearchHit]:
    """Run ``query`` on YAML searchers until one returns hits.

    Args:
        query (str): User query.
        config (ProvidersConfig | None): Registry; default ``load_providers()``.
        backends (Mapping[str, SearchFn] | None): id → callable. Default HTTP APIs.
        searcher_id (str | None): Restrict to one id.

    Returns:
        list[SearchHit]: First non-empty result list (failover on empty).

    Raises:
        KeyError: If ``searcher_id`` is not in the registry.
    """
    cfg = config or load_providers()
    table = dict(_default_backends() if backends is None else backends)
    hits: list[SearchHit] = []
    for spec in _select_specs(cfg, searcher_id):
        fn = table.get(spec.id)
        if fn is None:
            continue
        hits.extend(prefilter_hits(fn(query, spec), cfg.prefilter)[0])
        if hits:
            break
    return hits


def _select_specs(
    config: ProvidersConfig, searcher_id: str | None
) -> list[SearcherSpec]:
    specs = list(config.searchers)
    if searcher_id is None:
        return specs
    specs = [s for s in specs if s.id == searcher_id]
    if not specs:
        raise KeyError(searcher_id)
    return specs


def _rrf_fuse(
    batches: Sequence[Sequence[SearchHit]], *, k: int = 60
) -> list[SearchHit]:
    """Reciprocal-rank fusion across per-provider rankings.

    A URL returned by several providers outranks one returned by a single
    provider, so consensus sources lead the merged list. Ties keep first-seen
    (YAML) order, so the merge stays deterministic.

    Args:
        batches (Sequence[Sequence[SearchHit]]): One ranked batch per searcher.
        k (int): RRF constant; larger flattens provider rank differences.

    Returns:
        list[SearchHit]: Fused hits (still containing per-URL duplicates).
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
    near_distance: int | None = 6,
    sink: ResultSink | None = None,
) -> list[SearchHit]:
    """Send one ``query`` to every configured searcher at once and merge the hits.

    Searchers without a backend are skipped. A searcher that raises a transient
    error contributes no hits and does not affect the others. If the overall
    ``timeout_s`` budget expires, unfinished searchers are abandoned and the
    finished batches still answer. Merged hits are consensus-ranked (RRF across
    per-provider rankings) unless ``fuse=False`` keeps plain YAML order.

    Each provider's batch is prefiltered first (``config.prefilter``) so junk
    cannot gain rank from consensus. After fusion the hits are deduplicated by
    canonical URL, normalized, near-deduplicated, capped to ``limit`` (0 = no
    cap) and handed to ``sink``. A sink that raises ``OSError`` is logged and
    the hits are still returned. When every hit is rejected the result is empty
    and the API token total is not reported.

    Args:
        query (str): User query (a dork string works as-is).
        config (ProvidersConfig | None): Registry; default ``load_providers()``.
        backends (Mapping[str, SearchFn] | None): id → callable. Default HTTP APIs.
        searcher_id (str | None): Restrict to one id.
        max_workers (int): Thread cap; values below 1 are clamped to 1.
        timeout_s (float): Overall wall-clock budget for all searchers;
            ``<= 0`` waits unboundedly (each HTTP call still has its own timeout).
        limit (int): Max merged hits; ``0`` returns everything.
        fuse (bool): RRF consensus ranking across providers (default) instead
            of raw YAML-order concatenation.
        near_distance (int | None): Largest SimHash Hamming distance counted
            as a near-duplicate; ``None`` disables near-dedupe.
        sink (ResultSink | None): Receives the final hits when there are any.

    Returns:
        list[SearchHit]: Unique hits from all searchers, best first.

    Raises:
        KeyError: If ``searcher_id`` is not in the registry.
    """
    cfg = config or load_providers()
    table = dict(_default_backends() if backends is None else backends)
    jobs = [
        (spec, table[spec.id])
        for spec in _select_specs(cfg, searcher_id)
        if spec.id in table
    ]
    if not jobs:
        return []

    def run(job: tuple[SearcherSpec, SearchFn]) -> Sequence[SearchHit]:
        spec, fn = job
        try:
            return fn(query, spec)
        except TimeoutError, OSError, ConnectionError, ValueError:
            logger.warning("searcher %s failed", spec.id, exc_info=True)
            return []

    executor = ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(jobs))))
    wait = timeout_s if timeout_s and timeout_s > 0 else None
    pending = [(index, executor.submit(run, job)) for index, job in enumerate(jobs)]
    by_index: dict[int, Sequence[SearchHit]] = {}
    try:
        for future in as_completed([future for _, future in pending], timeout=wait):
            try:
                index = next(i for i, f in pending if f is future)
                by_index[index] = future.result()
            except Exception:
                logger.warning("searcher crashed", exc_info=True)
    except TimeoutError:
        for _, future in pending:
            future.cancel()
        logger.warning(
            "search budget %ss exceeded; abandoning slow searchers", timeout_s
        )
    finally:
        executor.shutdown(wait=False)
    batches = [by_index[index] for index in sorted(by_index)]
    api_tokens = sum(hit.api_tokens for batch in batches for hit in batch)
    clean = [prefilter_hits(batch, cfg.prefilter)[0] for batch in batches]
    merged = _rrf_fuse(clean) if fuse else [hit for batch in clean for hit in batch]
    hits = [normalize_hit(hit) for hit in dedupe_hits(merged)]
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
    logger.debug(
        "sink stored=%d skipped=%d %s", report.stored, report.skipped, report.detail
    )


__all__ = ["_rrf_fuse", "parallel_search", "registry_search", "searcher_ids"]
