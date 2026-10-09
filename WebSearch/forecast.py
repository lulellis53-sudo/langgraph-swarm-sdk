"""Search-volume history and forecast: ``websearch --forecast``.

Each search run is recorded (query, time, hit and provider counts) in the documents
database. The daily hit count per query becomes a series the ``Prediction`` engine
(``mlforecast`` + LightGBM, ``uv sync --extra forecast``) can forecast.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import pandas as pd

    from WebSearch.frontend.websearchers import SearchHit

_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_runs (
    id        INTEGER PRIMARY KEY,
    query     TEXT NOT NULL,
    ran_at    REAL NOT NULL,
    hits      INTEGER NOT NULL,
    providers INTEGER NOT NULL
)
"""
_SECONDS_PER_DAY = 86_400


class ForecastUnavailable(RuntimeError):
    """Raised when the forecast stack is missing or the history is too short."""


class _Engine(Protocol):
    """Minimal pandas forecasting interface expected by :func:`forecast_hits`."""

    def fit(self, df: pd.DataFrame) -> Any: ...

    def predict(self, horizon: int) -> pd.DataFrame: ...


def record_run(
    conn: sqlite3.Connection,
    query: str,
    hits: Sequence[SearchHit],
    *,
    at: float | None = None,
) -> None:
    """Append one run: how many hits and how many distinct providers answered."""
    conn.execute(_SCHEMA)
    providers = {sid for hit in hits for sid in (hit.searcher_id, *hit.also_from)}
    conn.execute(
        "INSERT INTO search_runs(query, ran_at, hits, providers) VALUES (?, ?, ?, ?)",
        (query, time.time() if at is None else at, len(hits), len(providers)),
    )
    conn.commit()


def run_series(conn: sqlite3.Connection, query: str) -> pd.DataFrame:
    """Daily mean hit count for ``query`` as a long frame (``unique_id``, ``ds``, ``y``).

    Days without a run are linearly interpolated so the series is contiguous.
    """
    import pandas as pd

    conn.execute(_SCHEMA)
    rows = conn.execute(
        "SELECT ran_at, hits FROM search_runs WHERE query = ? ORDER BY ran_at", (query,)
    ).fetchall()
    if not rows:
        return pd.DataFrame({"unique_id": [], "ds": [], "y": []})
    raw = pd.DataFrame(rows, columns=["ran_at", "hits"])
    raw["ds"] = pd.to_datetime(raw["ran_at"] // _SECONDS_PER_DAY, unit="D")
    daily = raw.groupby("ds")["hits"].mean().asfreq("D").interpolate()
    return pd.DataFrame({"unique_id": query, "ds": daily.index, "y": daily.to_numpy()})


def _default_engine() -> _Engine:
    """Lazily build the external forecasting engine or raise :class:`ForecastUnavailable`."""
    try:
        from Prediction import ForecastConfig, ForecastEngine  # ty: ignore[unresolved-import]
    except ImportError as exc:
        raise ForecastUnavailable(
            "Prediction engine not importable: put the Swarm repo root on PYTHONPATH and "
            "run `uv sync --extra forecast`"
        ) from exc
    return ForecastEngine(ForecastConfig(lags=(1, 2, 3), date_features=("dayofweek",)))


def forecast_hits(
    conn: sqlite3.Connection,
    query: str,
    *,
    horizon: int = 7,
    min_days: int = 14,
    engine_factory: Callable[[], _Engine] | None = None,
) -> list[tuple[str, float]]:
    """Forecast daily hit counts for ``query`` from its recorded history.

    Args:
        conn: Documents database.
        query: Exact query string that was recorded.
        horizon: Days ahead.
        min_days: Minimum days of history required.
        engine_factory: Engine builder (tests); default is ``Prediction.ForecastEngine``.

    Returns:
        ``(YYYY-MM-DD, predicted_hits)`` per future day, clipped at zero.

    Raises:
        ForecastUnavailable: Too little history, or the forecast stack is missing.
    """
    try:
        series = run_series(conn, query)
    except ImportError as exc:
        raise ForecastUnavailable("pandas missing: `uv sync --extra forecast`") from exc
    if len(series) < min_days:
        raise ForecastUnavailable(f"need >= {min_days} days of history, have {len(series)}")
    engine = (engine_factory or _default_engine)()
    engine.fit(series)
    prediction = engine.predict(horizon)
    return [
        (ds.strftime("%Y-%m-%d"), max(0.0, float(y)))
        for ds, y in zip(prediction["ds"], prediction["lgbm"], strict=True)
    ]


__all__ = ["ForecastUnavailable", "forecast_hits", "record_run", "run_series"]
