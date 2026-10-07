"""Brazilian RTX 5000+ and DDR5 digestion: leads, floors, alerts, forecasts."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from Prediction.br_hardware import (
    PRODUCTS,
    SOURCES,
    Lead,
    build_queries,
    connect,
    import_observation,
    rebuild_alerts,
    rebuild_floors,
    run_digest,
    write_forecast,
)


class _FlatForecast:
    """Forecast model that echoes the last training value."""

    def fit(self, frame: object) -> object:
        self.last = int(frame["y"].iloc[-1])  # type: ignore[index]
        return self

    def predict(self, horizon: int) -> pd.DataFrame:
        return pd.DataFrame({"lgbm": [self.last] * horizon})


def test_queries_name_the_product_the_brazilian_site_and_the_day() -> None:
    product = next(item for item in PRODUCTS if item.sku == "rtx-5090")
    source = next(item for item in SOURCES if item.name == "kabum")
    broad, coupon = build_queries(product, source, on=date(2026, 10, 5))

    assert '"RTX 5090"' in broad
    assert "site:kabum.com.br" in broad
    assert "after:2026-10-05 before:2026-10-06" in broad
    assert "cupom OR codigo OR promo OR desconto" in coupon
    memory = next(item for item in PRODUCTS if item.sku == "ddr5-32gb")
    memory_query, _ = build_queries(memory, source, on=date(2026, 10, 5))
    assert "DDR5 32GB" in memory_query


def test_digest_stores_leads_and_keeps_going_after_a_search_error() -> None:
    conn = connect(":memory:")
    calls: list[str] = []

    def search(query: str) -> list[Lead]:
        calls.append(query)
        if "pelando.com.br" in query:
            raise RuntimeError("blocked")
        if "RTX 5090" in query and "kabum.com.br" in query and "cupom" not in query:
            return [Lead("https://kabum.com.br/rtx", "RTX 5090", "oferta")]
        return []

    first = run_digest(conn, search, on=date(2026, 10, 5), at=1.0)
    assert len(calls) == first["queries"] == len(PRODUCTS) * len(SOURCES) * 2
    second = run_digest(conn, search, on=date(2026, 10, 5), at=2.0)

    assert first["failed"] == len(PRODUCTS) * 2
    assert first["stored"] == 1
    assert second["stored"] == 0
    row = conn.execute("SELECT sku, url FROM leads").fetchone()
    assert row["sku"] == "rtx-5090"
    assert row["url"] == "https://kabum.com.br/rtx"
    assert conn.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0] == 0


def test_verified_pix_floor_ignores_used_card_and_leads() -> None:
    conn = connect(":memory:")
    import_observation(
        conn,
        sku="ddr5-32gb",
        source="kabum",
        url="https://kabum.com.br/a",
        observed_on="2026-10-05",
        amount_cents=90000,
        payment="pix",
        condition="new",
        data_origin="observed",
        evidence="receipt",
    )
    import_observation(
        conn,
        sku="ddr5-32gb",
        source="pichau",
        url="https://pichau.com.br/a",
        observed_on="2026-10-05",
        amount_cents=80000,
        payment="pix",
        condition="new",
        data_origin="observed",
        evidence="receipt",
    )
    import_observation(
        conn,
        sku="ddr5-32gb",
        source="olx",
        url="https://olx.com.br/a",
        observed_on="2026-10-05",
        amount_cents=1000,
        payment="pix",
        condition="used",
        data_origin="observed",
        evidence="photo",
    )
    import_observation(
        conn,
        sku="ddr5-32gb",
        source="magalu",
        url="https://magazineluiza.com.br/a",
        observed_on="2026-10-05",
        amount_cents=1000,
        payment="card",
        condition="new",
        data_origin="observed",
        evidence="receipt",
    )

    assert rebuild_floors(conn) == 2
    pix = conn.execute("SELECT floor_cents, n FROM daily_floors WHERE payment = 'pix'").fetchone()
    assert pix["floor_cents"] == 80000
    assert pix["n"] == 2


def test_alert_fires_at_seventy_percent_and_skips_a_short_history() -> None:
    conn = connect(":memory:")
    start = date(2026, 9, 1)
    for offset in range(5):
        import_observation(
            conn,
            sku="rtx-5070",
            source="kabum",
            url=f"https://kabum.com.br/{offset}",
            observed_on=(start + timedelta(days=offset)).isoformat(),
            amount_cents=100000,
            payment="pix",
            condition="new",
            data_origin="observed",
            evidence="receipt",
        )
    import_observation(
        conn,
        sku="rtx-5070",
        source="kabum",
        url="https://kabum.com.br/sale",
        observed_on="2026-09-10",
        amount_cents=70000,
        payment="pix",
        condition="new",
        data_origin="observed",
        evidence="receipt",
    )
    rebuild_floors(conn)
    assert rebuild_alerts(conn) == 1
    alert = conn.execute("SELECT floor_cents, baseline_n FROM deal_alerts").fetchone()
    assert alert["floor_cents"] == 70000
    assert alert["baseline_n"] == 5


def test_synthetic_prices_do_not_alert() -> None:
    conn = connect(":memory:")
    for offset in range(6):
        import_observation(
            conn,
            sku="rtx-5080",
            source="terabyte",
            url=f"https://terabyteshop.com.br/{offset}",
            observed_on=(date(2026, 9, 1) + timedelta(days=offset)).isoformat(),
            amount_cents=1000,
            payment="pix",
            condition="new",
            data_origin="synthetic",
            evidence="fixture",
        )
    rebuild_floors(conn)
    assert rebuild_alerts(conn) == 0


def test_forecast_stays_unavailable_until_fourteen_floors() -> None:
    conn = connect(":memory:")
    for offset in range(13):
        import_observation(
            conn,
            sku="rtx-5090",
            source="amazon-br",
            url=f"https://amazon.com.br/{offset}",
            observed_on=(date(2026, 9, 1) + timedelta(days=offset)).isoformat(),
            amount_cents=1000000 + offset,
            payment="pix",
            condition="new",
            data_origin="observed",
            evidence="receipt",
        )
    rebuild_floors(conn)
    assert write_forecast(conn, "rtx-5090", engine=_FlatForecast(), cutoff="2026-09-13") == (
        "unavailable"
    )
    import_observation(
        conn,
        sku="rtx-5090",
        source="amazon-br",
        url="https://amazon.com.br/14",
        observed_on="2026-09-14",
        amount_cents=1000013,
        payment="pix",
        condition="new",
        data_origin="observed",
        evidence="receipt",
    )
    rebuild_floors(conn)
    assert write_forecast(conn, "rtx-5090", engine=_FlatForecast(), cutoff="2026-09-14") == "ready"
    row = conn.execute(
        "SELECT point_cents, status FROM predictions WHERE cutoff = '2026-09-14'"
    ).fetchone()
    assert row["status"] == "ready"
    assert row["point_cents"] == 1000013


def test_import_rejects_a_snippet_without_evidence() -> None:
    conn = connect(":memory:")
    with pytest.raises(ValueError, match="evidence"):
        import_observation(
            conn,
            sku="ddr5-16gb",
            source="promobit",
            url="https://promobit.com.br/x",
            observed_on="2026-10-05",
            amount_cents=50000,
            payment="pix",
            condition="new",
            data_origin="observed",
            evidence="  ",
        )
