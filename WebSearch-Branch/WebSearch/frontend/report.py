"""Per-provider search diagnostics: who answered, what the filters dropped, and why.

``parallel_search`` merges silently by design. :func:`search_report` runs the same
stages one provider at a time and keeps the counts, so a provider that fails closed
(missing key, blocked, empty) is visible instead of just absent.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from WebSearch.backend.prefilter import prefilter_hits
from WebSearch.frontend.hits import near_dedupe, normalize_hit
from WebSearch.frontend.websearchers import (
    ProvidersConfig,
    SearcherSpec,
    SearchFn,
    SearchHit,
    _rrf_fuse,
    _select_specs,
    builtin_searchers,
    dedupe_hits,
    env_base,
    env_key,
    load_providers,
    shared_executor,
)


@dataclass(frozen=True, slots=True)
class ProviderReport:
    """One provider's run.

    Attributes:
        id: Searcher id.
        status: ``ok``, ``empty`` (answered, nothing kept), ``error`` or ``no_backend``.
        error: Exception type name only (messages can embed URLs with keys).
        needs_credentials: The spec names an API key or base-URL env var.
        credentials_set: Those credentials resolve (env or Keychain). Never the value.
        raw: Hits returned by the provider.
        kept: Hits left after the prefilter.
        rejected: Prefilter rejects by reason.
        api_tokens: Tokens the search API itself reported.
        ms: Wall time of the call.
    """

    id: str
    status: str
    error: str = ""
    needs_credentials: bool = False
    credentials_set: bool = True
    raw: int = 0
    kept: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    api_tokens: int = 0
    ms: float = 0.0


@dataclass(frozen=True, slots=True)
class SearchReport:
    """Whole run: providers plus the merge stages.

    Attributes:
        query: Exact query sent to every provider.
        providers: One entry per selected searcher.
        kept: Hits left after every provider's prefilter, before merging.
        exact_dupes: Dropped as the same canonical URL.
        near_dupes: Dropped as SimHash near-duplicates.
        final: Hits returned.
        hits: The final hits.
    """

    query: str
    providers: list[ProviderReport]
    kept: int
    exact_dupes: int
    near_dupes: int
    final: int
    hits: list[SearchHit]

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return asdict(self)


def _credentials(spec: SearcherSpec) -> tuple[bool, bool]:
    needs = bool(spec.api_key_env or spec.base_url_env)
    if not needs:
        return False, True
    ok = (not spec.api_key_env or bool(env_key(spec))) and (
        not spec.base_url_env or bool(env_base(spec))
    )
    return True, ok


def _run_one(
    spec: SearcherSpec, fn: SearchFn | None, query: str, cfg: ProvidersConfig
) -> tuple[ProviderReport, list[SearchHit]]:
    needs, have = _credentials(spec)
    if fn is None:
        return ProviderReport(
            spec.id, "no_backend", needs_credentials=needs, credentials_set=have
        ), []
    start = time.perf_counter()
    try:
        raw = list(fn(query, spec))
        error = ""
    except Exception as exc:  # provider boundary: any failure becomes a report row
        raw, error = [], type(exc).__name__
    ms = round((time.perf_counter() - start) * 1000, 1)
    kept, rejected = prefilter_hits(raw, cfg.prefilter)
    status = "error" if error else ("ok" if kept else "empty")
    report = ProviderReport(
        spec.id,
        status,
        error=error,
        needs_credentials=needs,
        credentials_set=have,
        raw=len(raw),
        kept=len(kept),
        rejected=dict(Counter(r.reason for r in rejected)),
        api_tokens=sum(h.api_tokens for h in raw),
        ms=ms,
    )
    return report, kept


def search_report(
    query: str,
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    searcher_id: str | None = None,
    timeout_s: float = 30.0,
    near_distance: int = 6,
    limit: int = 0,
) -> SearchReport:
    """Run ``query`` on every selected provider and report each stage.

    Providers run concurrently on the shared executor; one that exceeds ``timeout_s``
    is reported as ``error: TimeoutError``. The merge mirrors ``parallel_search``:
    RRF fuse, canonical-URL dedupe, normalize, near-dedupe.

    Raises:
        KeyError: If ``searcher_id`` is not in the registry.
    """
    cfg = config or load_providers()
    table = dict(builtin_searchers() if backends is None else backends)
    specs = _select_specs(cfg, searcher_id)
    executor = shared_executor()
    futures = [executor.submit(_run_one, s, table.get(s.id), query, cfg) for s in specs]
    deadline = time.monotonic() + timeout_s if timeout_s > 0 else None
    reports: list[ProviderReport] = []
    batches: list[Sequence[SearchHit]] = []
    for spec, future in zip(specs, futures, strict=True):
        wait = None if deadline is None else max(0.0, deadline - time.monotonic())
        try:
            report, kept = future.result(timeout=wait)
        except TimeoutError:
            future.cancel()
            needs, have = _credentials(spec)
            report = ProviderReport(
                spec.id, "error", "TimeoutError", needs_credentials=needs, credentials_set=have
            )
            kept = []
        reports.append(report)
        batches.append(kept)
    kept_total = sum(len(batch) for batch in batches)
    unique = dedupe_hits(_rrf_fuse(batches))
    normalized = [normalize_hit(h) for h in unique]
    final = near_dedupe(normalized, max_distance=near_distance)
    near = len(normalized) - len(final)
    if limit > 0:
        final = final[:limit]
    return SearchReport(
        query=query,
        providers=reports,
        kept=kept_total,
        exact_dupes=kept_total - len(unique),
        near_dupes=near,
        final=len(final),
        hits=final,
    )


__all__ = ["ProviderReport", "SearchReport", "search_report"]
