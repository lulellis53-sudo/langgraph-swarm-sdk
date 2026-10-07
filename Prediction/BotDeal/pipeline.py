"""MultiWebsearch → Scrapers → Normalize pipeline, one YAML prompt, all searchers.

Stages (config in ``multiwebsearch.yaml``):
1. Fan ONE prompt template out to every enabled WebSearch searcher, one dork
   per catalog site (OR-grouped model + alias terms, ``after:``/``before:``).
2. Scrape the top hits with the crawler chain from ``providers.yaml`` and
   extract/normalize page text.
3. Normalize hits into ``product.schema.json`` records, store them in the
   day-partitioned Parquet, and emit per-SKU max/avg/min stats plus a digest
   for the orchestrator — whose findings feed back into WebSearch and the
   forecast engine every turn.

Run from ~/BotDeal with the lane venv:

    PYTHONPATH="$HOME/BotDeal:$HOME/Swarm-Prediction" \\
      ~/Swarm-Prediction/.venv/bin/python -m Prediction.BotDeal.pipeline
"""

from __future__ import annotations

import datetime as dt
import re
import statistics
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import yaml
from Prediction import harvest
from Prediction.BotDeal.database import append_products, day_dir_for_date
from Prediction.BotDeal.discovery import products_from_hits
from Prediction.BotDeal.hardware import load_catalog
from Prediction.br_hardware import market_today

PIPELINE_YAML = Path(__file__).resolve().parent / "multiwebsearch.yaml"

_PRICE = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)")


@lru_cache(maxsize=4)
def _config(path: Path, stamp: float) -> dict[str, Any]:
    del stamp
    return yaml.safe_load(path.read_text())


def load_pipeline(path: Path | None = None) -> dict[str, Any]:
    """Parse ``multiwebsearch.yaml`` (re-reads when the file changes)."""
    target = path or PIPELINE_YAML
    return _config(target, target.stat().st_mtime)


def _alias_terms(term: str, aliases: dict[str, list[str]]) -> list[str]:
    """Expand alias spellings: 'Ryzen 7 9800X3D' also matches '9800XD'."""
    terms = [term]
    for marker, spellings in aliases.items():
        if marker.lower() in term.lower():
            for spelling in spellings:
                terms.append(term.lower().replace(marker.lower(), spelling))
    return terms


def _model_or_group(terms: list[str]) -> str:
    return "(" + "|".join(f'"{t}"' if " " in t else t for t in terms) + ")"


def _site_query(
    terms: list[str],
    *,
    prompt: str,
    site: str | None,
    window_days: int,
    aliases: dict[str, list[str]],
) -> str:
    """One dork: a real OR-group of every (aliased) model term, then prompt words.

    ``("Ryzen 9 9950X3D"|"Ryzen 9 9950XD"|…) AND (preço|oferta) site:… — each
    term is its own OR alternative, never one giant quoted phrase.
    """
    from WebSearch.frontend.dorks import dork

    today = dt.date.today()
    all_terms: list[str] = []
    for term in terms:
        all_terms.extend(t for t in _alias_terms(term, aliases) if t not in all_terms)
    return dork(
        all_terms,
        *(prompt.split()),
        site=site,
        after=today - dt.timedelta(days=window_days) if window_days > 0 else None,
        before=today if window_days > 0 else None,
    )


def _scrape(url: str, *, timeout_s: int) -> str:
    """Fetch one page through the security-preflight and extract its text."""
    from WebSearch.backend.docs import extract_and_normalize

    if not url.startswith(("http://", "https://")):
        return ""
    host = url.split("/")[2] if "://" in url else ""
    if not host or host.split(":")[0] in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return ""
    try:
        response = httpx.get(
            url,
            timeout=timeout_s,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (BotDeal price harvest)"},
        )
        response.raise_for_status()
    except Exception:
        return ""
    doc = extract_and_normalize(response.text, url)
    return doc.text[:4000]


def run(*, skus: list[str] | None = None, limit: int = 10) -> dict[str, Any]:
    """Execute the pipeline and return the digest for the orchestrator."""
    config = load_pipeline()
    catalog = load_catalog()
    prompt = str(config["prompt"])
    aliases = config.get("aliases", {})
    window_days = int(config.get("window_days", 7))
    per_site = bool(config.get("per_site", True))
    scrape_top = int(config.get("scrape", {}).get("top", 3))
    scrape_timeout = int(config.get("scrape", {}).get("timeout_s", 15))
    wanted = skus or list(config.get("skus", [])) or [p.sku for p in catalog.products]

    from WebSearch.agent_tools import search_hits

    digest: dict[str, Any] = {"skus": {}, "records": 0}
    today = market_today()
    month = today.strftime("%B")
    records: list[dict[str, Any]] = []
    for sku in wanted:
        product = next(item for item in catalog.products if item.sku == sku)
        sites = (
            [source.domain for source in catalog.sources if source.kind != "social"]
            if per_site
            else [None]
        )
        prices: list[float] = []
        scraped: list[str] = []
        for site in sites:
            query = _site_query(
                list(product.terms),
                prompt=prompt,
                site=site,
                window_days=window_days,
                aliases=aliases,
            )
            try:
                hits = search_hits(query, limit=limit)
            except Exception as exc:
                digest.setdefault("errors", []).append(f"{sku}/{site}: {type(exc).__name__}: {exc}")
                continue
            for hit in hits[:limit]:
                source = harvest.source_for(hit.url)
                if source is None:
                    continue
                match = next(
                    (
                        c
                        for c in (harvest.parse_brl_cents(t) for t in (hit.title, hit.snippet))
                        if c is not None
                    ),
                    None,
                )
                plausible = catalog.plausible.get(sku)
                price = match / 100 if match is not None else None
                if (
                    match is not None
                    and plausible
                    and plausible[0] * 100 <= match <= plausible[1] * 100
                ):
                    prices.append(price)
                if len(scraped) < scrape_top:
                    text = _scrape(hit.url, timeout_s=scrape_timeout)
                    if text:
                        scraped.append(f"{hit.url}: {text[:300]}")
                        page_match = _PRICE.search(text)
                        if page_match:
                            cents = harvest.parse_brl_cents(page_match.group(0))
                            if (
                                cents
                                and plausible
                                and plausible[0] * 100 <= cents <= plausible[1] * 100
                            ):
                                prices.append(cents / 100)
                records.extend(
                    products_from_hits(
                        [hit],
                        query=query,
                        unique_id=sku,
                        observed_at=today,
                        currency="BRL" if price is not None else None,
                    )
                )
                if records and records[-1]["url"] == hit.url and price is not None:
                    records[-1]["price"] = price
        if prices:
            digest["skus"][sku] = {
                "min": min(prices),
                "avg": round(statistics.mean(prices), 2),
                "max": max(prices),
                "n": len(prices),
            }
        for record in records:
            if record["unique_id"] == sku:
                record.setdefault("observed_at", today.isoformat())
        print(f"{sku}: {len(prices)} prices, {len(scraped)} pages scraped")
    if records:
        append_products(records, month=month, day=today.day)
        digest["records"] = len(records)
        digest["parquet"] = str(day_dir_for_date(today) / "products.parquet")
    return digest


def multi_search(
    skus: list[str], *, window_days: int = 7, limit: int = 10, store_db: str = "offers.db"
) -> dict[str, Any]:
    """One OR-group dork for several SKUs, run once per catalog site.

    Emits the user's pattern — ``(9950X3D|9950XD|9950X|9800X3D|9800XD|9800X)
    (preço|oferta) site:… after:… before:…`` — across every non-social source,
    resolves each hit back to one SKU by longest-match, and stores both the
    offers-store observation and the Parquet record per hit.
    """
    config = load_pipeline()
    catalog = load_catalog()
    aliases = config.get("aliases", {})
    scrape_timeout = int(config.get("scrape", {}).get("timeout_s", 15))
    products = {p.sku: p for p in catalog.products if p.sku in skus}
    missing = set(skus) - set(products)
    if missing:
        raise SystemExit(f"unknown skus: {sorted(missing)}")
    or_terms: list[str] = []
    for product in products.values():
        for term in product.terms:
            or_terms.extend(t for t in _alias_terms(term, aliases) if t not in or_terms)
    today = market_today()
    day = today.isoformat()
    month = today.strftime("%B")

    from Prediction.BotDeal.sniper import match_sku
    from Prediction.br_hardware import connect, import_observation, rebuild_alerts, rebuild_floors
    from WebSearch.agent_tools import search_hits

    db = connect(store_db)
    digest: dict[str, Any] = {"hits": 0, "prices": {}, "errors": []}
    records: list[dict[str, Any]] = []
    try:
        for source in catalog.sources:
            if source.kind == "social":
                continue
            query = _site_query(
                or_terms,
                prompt="preço oferta",
                site=source.domain,
                window_days=window_days,
                aliases={},
            )
            try:
                hits = search_hits(query, limit=limit)
            except Exception as exc:
                digest["errors"].append(f"{source.name}: {type(exc).__name__}: {exc}")
                continue
            for hit in hits[:limit]:
                # URLs carry the model without spaces ("ryzen-9-9950x3d"):
                # normalize separators so spaced catalog terms still match.
                url_words = hit.url.replace("-", " ").replace("/", " ")
                matched = match_sku(f"{hit.title} {hit.snippet} {url_words}")
                if matched is None:
                    continue
                sku, _term = matched
                plausible = catalog.plausible.get(sku)
                # Prices live on the PAGE, not in search snippets: scrape the
                # hit, then fall back to the snippet price when the page fails.
                page_text = _scrape(hit.url, timeout_s=scrape_timeout)
                cents = next(
                    (
                        c
                        for c in (
                            harvest.parse_brl_cents(m.group(0))
                            for m in _PRICE.finditer(page_text)
                        )
                        if c is not None
                    ),
                    None,
                )
                if cents is None:
                    cents = next(
                        (
                            c
                            for c in (harvest.parse_brl_cents(t) for t in (hit.title, hit.snippet))
                            if c is not None
                        ),
                        None,
                    )
                if (
                    cents is None
                    or not plausible
                    or not plausible[0] * 100 <= cents <= plausible[1] * 100
                ):
                    continue
                try:
                    import_observation(
                        db,
                        sku=sku,
                        source=source.name,
                        url=hit.url,
                        observed_on=day,
                        amount_cents=cents,
                        payment="card",
                        condition="used" if source.name == "olx" else "new",
                        data_origin="observed",
                        evidence=f"multi-site dork hit: {hit.title[:120]}",
                        verification="snippet",
                    )
                except ValueError as exc:
                    digest["errors"].append(f"{sku}/{source.name}: {exc}")
                    continue
                price = cents / 100
                stats = digest["prices"].setdefault(sku, [])
                stats.append(price)
                records.extend(
                    products_from_hits(
                        [hit],
                        query=query,
                        unique_id=sku,
                        observed_at=today,
                        currency="BRL",
                    )
                )
                if records and records[-1]["url"] == hit.url:
                    records[-1]["price"] = price
                digest["hits"] += 1
        rebuild_floors(db)
        rebuild_alerts(db)
    finally:
        db.close()
    if records:
        append_products(records, month=month, day=today.day)
        digest["parquet"] = str(day_dir_for_date(today) / "products.parquet")
    digest["prices"] = {
        sku: {"min": min(v), "avg": round(statistics.mean(v), 2), "max": max(v), "n": len(v)}
        for sku, v in digest["prices"].items()
    }
    return digest


def monthly_stats(month: str) -> dict[str, dict[str, float]]:
    """Per-SKU max/avg/min of parsed prices for one month of Parquet data."""
    import polars as pl
    from Prediction.BotDeal.database import read_month

    frame = read_month(month)
    if frame.is_empty() or "price" not in frame.columns:
        return {}
    priced = frame.filter(pl.col("price").is_not_null())
    if priced.is_empty():
        return {}
    grouped = priced.group_by("unique_id").agg(
        pl.col("price").max().alias("max"),
        pl.col("price").mean().alias("avg"),
        pl.col("price").min().alias("min"),
        pl.len().alias("n"),
    )
    return {
        row["unique_id"]: {
            "max": round(float(row["max"]), 2),
            "avg": round(float(row["avg"]), 2),
            "min": round(float(row["min"]), 2),
            "n": int(row["n"]),
        }
        for row in grouped.iter_rows(named=True)
    }


def _price_stats_row(row: dict[str, Any]) -> str:
    stats = "min R${min:,.2f} | avg R${avg:,.2f} | max R${max:,.2f} (n={n})".format(**row)
    return stats


if __name__ == "__main__":
    import json
    import sys

    digest = run()
    stats = monthly_stats(market_today().strftime("%B"))
    print("=== monthly max/avg/min per SKU ===")
    for sku, row in stats.items():
        print(f"{sku}: {_price_stats_row(row)}")
    print(json.dumps(digest, indent=2, default=str), file=sys.stderr)
