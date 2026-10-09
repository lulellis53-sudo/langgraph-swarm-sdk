"""End-to-end offline test for technews.prediction: store -> frame -> forecast -> CLI."""

import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from technews.prediction import (
    FeatureStore,
    TrendForecaster,
    build_frame,
    ready_series,
)

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the prediction CLI in an isolated process against the local sources."""
    env = dict(os.environ, PYTHONPATH=SRC)
    return subprocess.run(
        [sys.executable, "-m", "technews.prediction", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


HORIZON = 7
CATEGORIES = ("ai", "hardware")
DAYS = 20


def _seed(store: FeatureStore) -> None:
    """Seed DAYS of daily counts for each category."""
    store.ensure_schema()
    start = date(2026, 9, 1)
    for offset in range(DAYS):
        day = (start + timedelta(days=offset)).isoformat()
        for index, category in enumerate(CATEGORIES):
            store.upsert_daily(day, category, 5 + offset + index)


def test_store_frame_forecast_movers(tmp_path: Path) -> None:
    with FeatureStore(tmp_path / "features.db") as store:
        _seed(store)
        counts = store.daily_counts()
        assert len(counts) == DAYS * len(CATEGORIES)
        assert sorted(store.categories()) == sorted(CATEGORIES)

        frame = build_frame(counts)
        assert set(frame.columns) >= {"unique_id", "ds", "y"}
        assert sorted(ready_series(frame)) == sorted(CATEGORIES)

        forecaster = TrendForecaster(horizon=HORIZON)
        assert not forecaster.is_fitted
        forecaster.fit(frame)
        assert forecaster.is_fitted

        points = forecaster.predict()
        assert len(points) == HORIZON * len(CATEGORIES)
        per_category: dict[str, int] = {}
        import math

        for point in points:
            assert math.isfinite(point.yhat)
            per_category[point.category] = per_category.get(point.category, 0) + 1
        assert per_category == {category: HORIZON for category in CATEGORIES}

        movers = forecaster.movers(frame)
        assert movers, "movers must not be empty"
        assert {category for category, _ in movers} == set(CATEGORIES)


def test_prediction_cli_forecast(tmp_path: Path) -> None:
    with FeatureStore(tmp_path / "features.db") as store:
        _seed(store)
    result = _run_cli("forecast", "--db", str(tmp_path / "features.db"), "--horizon", str(HORIZON))
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1 + HORIZON * len(CATEGORIES)
    assert lines[0].startswith("category")


def test_prediction_cli_backfill(tmp_path: Path) -> None:
    articles = _make_articles_db(tmp_path / "articles.db")
    result = _run_cli(
        "backfill", "--db", str(tmp_path / "features.db"), "--articles", str(articles)
    )
    assert result.returncode == 0, result.stderr
    assert "backfilled" in result.stdout
    with FeatureStore(tmp_path / "features.db") as store:
        assert store.daily_counts(), "backfill must produce rows"


def _make_articles_db(path: Path) -> Path:
    """Create a minimal articles DB matching the store's backfill query."""
    import sqlite3

    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, "
            "category TEXT, published TEXT)"
        )
        conn.executemany(
            "INSERT INTO articles(title, category, published) VALUES (?, ?, ?)",
            [
                ("a", "ai", "2026-09-01T10:00:00"),
                ("b", "ai", "2026-09-02T10:00:00"),
                ("c", "hardware", "2026-09-01T11:00:00"),
            ],
        )
    return path
