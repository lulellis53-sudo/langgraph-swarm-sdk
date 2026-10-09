"""Tests for the promodeals_mcp server (temp DB, no network)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from Prediction import mcp_server as srv
from Prediction.br_hardware import connect, import_observation, rebuild_alerts, rebuild_floors


@pytest.fixture()
def seeded_db(tmp_path: Path) -> Path:
    """A offers DB with 6 days of RTX 5060/5090 observations and one alert-day."""
    db = tmp_path / "offers.db"
    conn = connect(db)
    for day_index in range(6):
        day = f"2026-10-0{day_index + 1}"
        # 5060 around R$2200 (deal day on day 6), 5090 around R$20000.
        floor_5060 = 2200 if day_index < 5 else 2000
        import_observation(
            conn,
            sku="rtx-5060",
            source="kabum",
            url=f"https://www.kabum.com.br/p/{day_index}",
            observed_on=day,
            amount_cents=floor_5060 * 100,
            payment="card",
            condition="new",
            data_origin="observed",
            evidence="test fixture",
            verification="verified",
        )
        import_observation(
            conn,
            sku="rtx-5090",
            source="terabyte",
            url=f"https://www.terabyteshop.com.br/p/{day_index}",
            observed_on=day,
            amount_cents=20000 * 100,
            payment="card",
            condition="new",
            data_origin="observed",
            evidence="test fixture",
            verification="snippet",
        )
    rebuild_floors(conn)
    rebuild_alerts(conn)
    conn.close()
    return db


@pytest.fixture()
def conn_over(seeded_db: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """Open the seeded DB with PROMODEALS_DB pointed at it."""
    monkeypatch.setenv("PROMODEALS_DB", str(seeded_db))
    return srv.connect_db()


def test_floors_core_reports_verdicts(conn_over: sqlite3.Connection) -> None:
    payload = json.loads(json.dumps(srv.floors_core(conn_over)))
    skus = {item["sku"]: item for item in payload["skus"]}
    assert skus["rtx-5060"]["latest_floor_brl"] == 2000.0
    assert skus["rtx-5060"]["verdict"].startswith("DEAL")
    assert skus["rtx-5090"]["latest_floor_brl"] == 20000.0
    assert skus["rtx-5090"]["verdict"].startswith("DEAL")
    assert skus["rtx-5090"]["history_days"] == 6


def test_alerts_core_needs_history(conn_over: sqlite3.Connection) -> None:
    # 6 days exist, but alerts need 5 PRIOR days: day 6 qualifies for 5060.
    alerts = srv.alerts_core(conn_over)
    assert isinstance(alerts, list)
    for alert in alerts:
        assert alert["baseline_days"] >= 5


def test_nearest_core_ranks_query_sku(conn_over: sqlite3.Connection) -> None:
    hits = srv.nearest_core(conn_over, "RTX 5060 barata oferta", k=5)
    assert hits, "KNN returned no hits"
    assert all(h["sku"] in {"rtx-5060", "rtx-5090"} for h in hits)
    assert hits[0]["sku"] == "rtx-5060"
    assert hits[0]["distance"] <= min(h["distance"] for h in hits)


def test_nearest_core_condition_filter(conn_over: sqlite3.Connection) -> None:
    hits = srv.nearest_core(conn_over, "placa de video", k=10, condition="new")
    assert all(h["condition"] == "new" for h in hits)


def test_server_registers_four_tools() -> None:
    tools = asyncio.run(srv.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "promodeals_price_floors",
        "promodeals_deal_alerts",
        "promodeals_nearest_prices",
        "promodeals_harvest",
    }


def test_tool_input_models_forbid_extras() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        srv.NearestInput(query="rtx 5060", bogus="x")


def test_load_lexical_embedder_is_deterministic() -> None:
    embedder = srv.load_lexical_embedder(1024)
    first = embedder.embed(["rtx 5060 kabum"])[0]
    second = embedder.embed(["rtx 5060 kabum"])[0]
    assert (first == second).all()
    assert first.shape == (1024,)
