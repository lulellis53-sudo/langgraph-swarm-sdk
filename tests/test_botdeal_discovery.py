"""Tests for product discovery dorks (AND/OR, after/before) and hit normalization.

Run from ~/BotDeal with the lane venv:

    PYTHONPATH="$HOME/BotDeal:$HOME/Swarm-Prediction" \\
      ~/Swarm-Prediction/.venv/bin/python -m pytest tests/test_botdeal_discovery.py -q
"""

from __future__ import annotations

import datetime as dt

from Prediction.BotDeal.discovery import find_products, product_dork, products_from_hits
from WebSearch.agent_tools import search
from WebSearch.frontend.dorks import parse_dork
from WebSearch.frontend.websearchers import ProvidersConfig, SearcherSpec, SearchHit


def test_product_dork_composes_or_and_dates() -> None:
    query = product_dork(
        "rtx 5060",
        after=dt.date(2026, 9, 1),
        before="2026-09-30",
    )
    assert query == (
        '(preço|price|comprar) AND ("rtx 5060") -usado -olx after:2026-09-01 before:2026-09-30'
    )


def test_product_dork_accepts_sites_and_brand() -> None:
    query = product_dork(
        "rtx 5090",
        brand="NVIDIA",
        sites=("kabum.com.br",),
        exclude=("usado",),
    )
    assert query == ('(preço|price|comprar) AND ("NVIDIA rtx 5090") site:kabum.com.br -usado')


def test_dork_roundtrip_parses_dates_and_groups() -> None:
    parsed = parse_dork(
        '(preço|price|comprar) AND ("rtx 5060") -usado after:2026-09-01 before:2026-09-30'
    )
    assert parsed.after == "2026-09-01"
    assert parsed.before == "2026-09-30"
    assert "rtx 5060" in parsed.terms
    assert "usado" in parsed.exclude_terms


def test_products_from_hits_normalizes_and_validates() -> None:
    hits = [
        SearchHit(
            title="RTX 5090 barata",
            url="https://www.kabum.com.br/rtx5090",
            snippet="R$ 14.999 em 2026-10-06",
            searcher_id="fake",
        ),
        SearchHit(title="junk", url="javascript:void(0)", snippet="", searcher_id="fake"),
    ]
    records = products_from_hits(
        hits,
        query="probe",
        unique_id="rtx-5090",
        observed_at=dt.date(2026, 10, 6),
    )
    assert len(records) == 1  # non-http hit dropped
    record = records[0]
    assert record["source"] == "kabum.com.br"  # www. stripped
    assert record["unique_id"] == "rtx-5090"
    assert record["price"] is None  # evidence mining owns prices
    assert record["observed_at"] == "2026-10-06"
    from Prediction.BotDeal.database import validate_record

    validate_record(record)  # schema-valid output, ready for the Parquet store


def test_find_products_end_to_end_fake_backend() -> None:
    config = ProvidersConfig(
        version=1,
        searchers=(SearcherSpec(id="fake", kind="websearcher", enabled=True),),
        extractor_order=("selectolax",),
    )

    def backend(query: str, spec: SearcherSpec) -> list[SearchHit]:
        del query, spec
        return [
            SearchHit(
                title="Placa RTX 5060",
                url="https://a.example/5060",
                snippet="On 2026-10-01 the RTX 5060 cost R$ 2400",
                searcher_id="fake",
            ),
        ]

    records = find_products(
        product_dork("rtx 5060"),
        unique_id="rtx-5060",
        config=config,
        backends={"fake": backend},
    )
    assert len(records) == 1
    assert records[0]["query"].startswith("(preço|price|comprar)")


def test_search_reports_disabled_and_no_backend_statuses() -> None:
    config = ProvidersConfig(
        version=1,
        searchers=(
            SearcherSpec(id="off", kind="websearcher", enabled=False),
            SearcherSpec(id="none", kind="websearcher", enabled=True),
        ),
        extractor_order=("selectolax",),
    )
    result = search("probe", config=config, backends={})
    assert result.status["off"].status == "disabled"
    assert result.status["none"].status == "not_implemented"
