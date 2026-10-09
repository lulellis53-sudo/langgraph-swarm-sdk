"""Offline tests for technews.prediction.mcp_server (temp DB, no network).

Runs against the real prediction modules; the WebSearch-backed harvester is
monkeypatched so no network is touched.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ARTICLES_SCHEMA = """
CREATE TABLE articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    published TEXT,
    excerpt TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    tags TEXT NOT NULL DEFAULT ''
);
"""


def _seed_articles(path: Path, rows: list[tuple[str, str, str]]) -> None:
    """rows: (day_iso, category, url_suffix); one article per row at 10:00 UTC."""
    conn = sqlite3.connect(path)
    conn.executescript(ARTICLES_SCHEMA)
    conn.executemany(
        "INSERT INTO articles(url, source, category, title, published, excerpt, "
        "content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (f"u{n}", "s", cat, f"t{n}", f"{day}T10:00:00+00:00", "e", f"h{n}")
            for n, (day, cat, _) in enumerate(rows, start=1)
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Feature DB with 20 days of one category — enough history to forecast."""
    db = tmp_path / "technews.db"
    base = date(2026, 9, 1)
    _seed_articles(
        db,
        [(str(base + timedelta(days=d)), "ai", str(d)) for d in range(20)],
    )
    monkeypatch.setenv("TECHNEWS_DB", str(db))
    from technews.prediction.mcp_server import refresh_core

    result = refresh_core()
    assert "error" not in result, f"seeding backfill must succeed: {result}"
    assert result["rows"] == 20
    return db


# --- tools -------------------------------------------------------------------------


def test_db_path_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from technews.prediction.mcp_server import db_path

    monkeypatch.setenv("TECHNEWS_DB", str(tmp_path / "x.db"))
    assert db_path() == tmp_path / "x.db"
    monkeypatch.delenv("TECHNEWS_DB")
    assert db_path() == Path("technews.db")


def test_forecast_categories(seeded_db: Path) -> None:
    from technews.prediction.mcp_server import technews_forecast_categories

    raw = asyncio.run(technews_forecast_categories(SimpleNamespace(horizon=3)))
    result = json.loads(raw)
    assert isinstance(result, list) and result, result
    assert {"category", "date", "yhat"} == set(result[0])
    assert len(result) == 3  # horizon 3 x 1 seeded category
    assert result[0]["category"] == "ai"


def test_top_movers(seeded_db: Path) -> None:
    from technews.prediction.mcp_server import movers_core, technews_top_movers

    core = movers_core()
    assert isinstance(core, list) and core
    assert {"category", "pct_change"} == set(core[0])
    raw = asyncio.run(technews_top_movers(None))
    assert json.loads(raw) == core


def test_search_topic_signal(seeded_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Harvester is monkeypatched: the tool layer must work without network."""
    from dataclasses import dataclass

    import technews.prediction.harvest as harvest_mod

    @dataclass(frozen=True, slots=True)
    class FakeSignal:
        topic: str
        query: str
        hits: int
        top_titles: list[str]
        source: str

    class FakeHarvester:
        def __init__(self, search_fn: object = None) -> None:
            self.search_fn = search_fn

        def check_topics(self, topics: list[str]) -> list[FakeSignal]:
            return [
                FakeSignal(t, f"{t} news", 3, [f"{t} rises"], "fake") for t in topics
            ]

    monkeypatch.setattr(harvest_mod, "TopicHarvester", FakeHarvester)
    from technews.prediction.mcp_server import technews_search_topic_signal

    raw = asyncio.run(technews_search_topic_signal(SimpleNamespace(topics=["llm agents"])))
    result = json.loads(raw)
    assert isinstance(result, list) and len(result) == 1
    assert result[0]["topic"] == "llm agents"
    assert {"topic", "query", "hits", "top_titles", "source"} == set(result[0])


def test_refresh_features(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "fresh.db"
    _seed_articles(
        db,
        [("2026-09-01", "ai", "a"), ("2026-09-02", "ai", "b"), ("2026-09-02", "web", "c")],
    )
    monkeypatch.setenv("TECHNEWS_DB", str(db))
    from technews.prediction.mcp_server import technews_refresh_features

    result = json.loads(asyncio.run(technews_refresh_features(None)))
    assert result == {"rows": 3}, result


def test_error_convention_empty_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TECHNEWS_DB", str(tmp_path / "empty.db"))
    from technews.prediction.mcp_server import forecast_core

    result = forecast_core()
    assert "error" in result


def test_server_registers_four_tools() -> None:
    try:
        from technews.prediction.mcp_server import mcp
    except ImportError:
        pytest.skip("mcp package not installed")
    tools = asyncio.run(mcp.list_tools())
    assert {t.name for t in tools} >= {
        "technews_forecast_categories",
        "technews_top_movers",
        "technews_search_topic_signal",
        "technews_refresh_features",
    }
