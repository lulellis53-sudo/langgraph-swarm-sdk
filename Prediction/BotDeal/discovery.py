"""Product discovery: Google dorks → WebSearch hits → schema'd product records.

Builds dork queries with OR groups (``any_of``) joined by ``AND`` plus
``after:``/``before:`` date bounds (see ``WebSearch.frontend.dorks``), runs
them through the vendored WebSearch tool, and normalizes every hit into a
record that validates against ``product.schema.json`` so
:mod:`Prediction.BotDeal.database` can store it as Parquet.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import urllib.parse
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

__all__ = ["PRODUCT_TERMS", "find_products", "product_dork", "products_from_hits"]

#: OR-group alternatives ANDed into every product query.
PRODUCT_TERMS = ("preço", "price", "comprar")


def product_dork(
    model: str,
    *,
    terms: Sequence[str] = PRODUCT_TERMS,
    brand: str | None = None,
    sites: Iterable[str] = (),
    exclude: Iterable[str] = ("usado", "olx"),
    after: dt.date | str | None = None,
    before: dt.date | str | None = None,
) -> str:
    """Build a product dork: ``(terms) AND (models) site:… -usado after:… before:…``.

    ``model`` alternatives are OR-grouped; pass extra spellings via ``model``'s
    ``|``-free list by calling :func:`product_dork` once per spelling or by
    giving ``brand``. Date bounds accept ``date`` objects or ``YYYY-MM-DD``.
    """
    from WebSearch.frontend.dorks import dork

    model_alternatives = [f"{brand} {model}".strip()] if brand else [model]
    return dork(
        list(terms),
        model_alternatives,
        site=" ".join(sites) if sites else None,
        exclude=exclude,
        after=after,
        before=before,
    )


def _host(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).netloc.removeprefix("www.") or "unknown"
    except ValueError:
        return "unknown"


def _hit_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def products_from_hits(
    hits: Iterable[Any],
    *,
    query: str,
    unique_id: str = "unknown",
    observed_at: dt.date | None = None,
    currency: str | None = None,
) -> list[dict[str, Any]]:
    """Normalize WebSearch hits into records valid for ``product.schema.json``.

    ``price`` stays ``None`` — evidence mining (``Prediction.web_evidence``)
    owns price extraction; this function only guarantees schema-shaped rows.
    """
    from Prediction.BotDeal.database import validate_record

    day = observed_at or dt.date.today()
    records: list[dict[str, Any]] = []
    for hit in hits:
        url = str(getattr(hit, "url", "") or "")
        if not url.startswith(("http://", "https://")):
            continue
        record: dict[str, Any] = {
            "unique_id": unique_id,
            "name": (str(getattr(hit, "title", "") or url)[:200]) or url,
            "source": _host(url),
            "url": url,
            "observed_at": day.isoformat(),
            "brand": None,
            "model": None,
            "price": None,
            "currency": currency,
            "condition": None,
            "seller": None,
            "in_stock": None,
            "snippet": str(getattr(hit, "snippet", "") or "") or None,
            "query": query,
            "confidence": None,
        }
        validate_record(record)
        records.append(record)
    seen: set[str] = set()
    deduped = [
        record for record in records if not (record["url"] in seen or seen.add(record["url"]))
    ]
    _ = _hit_id  # sha1 ids are available for callers that need opaque keys
    return deduped


def find_products(
    query: str,
    *,
    unique_id: str = "unknown",
    limit: int = 10,
    config: Mapping[str, Any] | None = None,
    backends: Mapping[str, Any] | None = None,
    searcher_id: str | None = None,
    timeout_s: float = 30.0,
) -> list[dict[str, Any]]:
    """Search the web for ``query`` and return schema-valid product records.

    Offline callers inject fake ``backends`` (id → callable), mirroring
    ``WebSearch.agent_tools.search_hits``.
    """
    from WebSearch.agent_tools import search_hits

    hits = search_hits(
        query,
        limit=limit,
        config=config,
        backends=backends,
        searcher_id=searcher_id,
        timeout_s=timeout_s,
    )
    return products_from_hits(hits, query=query, unique_id=unique_id)
