"""MCP server exposing the TechNews trend-prediction system.

Server name: ``technews_prediction_mcp`` (stdio transport). Tools:

- ``technews_forecast_categories``: per-category horizon forecast from the
  daily feature store (backfill-free read of daily_counts).
- ``technews_top_movers``: categories ranked by week-over-week pct change.
- ``technews_search_topic_signal``: live topic harvest (WebSearch signals).
- ``technews_refresh_features``: backfill the feature store from articles.

The database path comes from ``TECHNEWS_DB`` (default ``technews.db`` in the
current working directory — ``technews.store`` defines no default) so tests
can point it at a temporary database.

The ``mcp`` package is optional at import time: when absent, tools are still
defined as plain async functions (unit-testable offline) and only the server
registration is skipped.

Run with the project venv:
    uv run python -m technews.prediction.mcp_server
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

try:  # optional at import time so tests run without the mcp package
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer("technews_prediction_mcp")
    tool = mcp.tool
except ImportError:  # pragma: no cover - exercised only without mcp installed

    def tool(**_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """No-op stand-in for MCPServer.tool keeping tools unit-testable."""

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            return fn

        return decorator


DEFAULT_DB = Path("technews.db")  # technews.store defines no default path
_MODULE_HINT = "prediction modules unavailable (missing dep or not written); retry once integrated"


def db_path() -> Path:
    """Resolve the TechNews database path (``TECHNEWS_DB`` overrides)."""
    override = os.environ.get("TECHNEWS_DB", "").strip()
    return Path(override).expanduser() if override else DEFAULT_DB


def _error(exc: BaseException, hint: str = "") -> dict[str, Any]:
    """Structured error payload — the server's error convention."""
    payload: dict[str, Any] = {"error": f"{type(exc).__name__}: {exc}"}
    if hint:
        payload["hint"] = hint
    return payload


def _as_jsonable(obj: Any) -> Any:
    """Convert dataclass results to JSON-able dicts."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if hasattr(obj, "_asdict"):  # namedtuple
        return obj._asdict()
    return obj


def forecast_core(horizon: int = 7) -> list[dict[str, Any]] | dict[str, Any]:
    """Forecast daily counts per category over ``horizon`` days."""
    try:
        from technews.prediction.features import build_frame
        from technews.prediction.forecast import TrendForecaster
        from technews.prediction.store import FeatureStore
    except ImportError as exc:
        return _error(exc, _MODULE_HINT)
    try:
        store = FeatureStore(db_path())
        store.ensure_schema()
        counts = store.daily_counts()
        if not counts:
            return _error(
                ValueError("no daily counts in the feature store"),
                "run technews_refresh_features first",
            )
        frame = build_frame(counts)
        forecaster = TrendForecaster(horizon=horizon)
        forecaster.fit(frame)
        return [
            {"category": p.category, "date": str(p.date), "yhat": float(p.yhat)}
            for p in forecaster.predict()
        ]
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the caller
        return _error(exc)


def movers_core() -> list[dict[str, Any]] | dict[str, Any]:
    """Categories ranked by week-over-week pct change."""
    try:
        from technews.prediction.features import build_frame
        from technews.prediction.forecast import TrendForecaster
        from technews.prediction.store import FeatureStore
    except ImportError as exc:
        return _error(exc, "wait for the prediction modules, then retry")
    try:
        store = FeatureStore(db_path())
        store.ensure_schema()
        counts = store.daily_counts()
        if not counts:
            return _error(
                ValueError("no daily counts in the feature store"),
                "run technews_refresh_features first",
            )
        frame = build_frame(counts)
        forecaster = TrendForecaster()
        forecaster.fit(frame)
        movers = forecaster.movers(frame)
        return [{"category": category, "pct_change": float(value)} for category, value in movers]
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the caller
        return _error(exc)


def topic_signal_core(topics: list[str]) -> list[dict[str, Any]] | dict[str, Any]:
    """Live WebSearch signal for each requested topic."""
    try:
        from technews.prediction.harvest import TopicHarvester
    except ImportError as exc:
        return _error(exc, _MODULE_HINT)
    try:
        harvester = TopicHarvester(search_fn=None)
        signals = harvester.check_topics(topics)
        return [dict(_as_jsonable(s)) for s in signals]
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the caller
        return _error(exc)


def refresh_core() -> dict[str, Any]:
    """Backfill the feature store from the articles tables."""
    try:
        from technews.prediction.store import FeatureStore
    except ImportError as exc:
        return _error(exc, _MODULE_HINT)
    try:
        store = FeatureStore(db_path())
        store.ensure_schema()
        result = store.backfill_from_articles(db_path())
        rows = int(result) if isinstance(result, int) else len(result)
        return {"rows": rows}
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the caller
        return _error(exc)


# --- input models -----------------------------------------------------------------


try:
    from pydantic import BaseModel, ConfigDict, Field

    class ForecastInput(BaseModel):
        """Input model for the forecast tool."""

        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

        horizon: int = Field(default=7, description="Days to forecast ahead", ge=1, le=90)

    class MoversInput(BaseModel):
        """Input model for the movers tool."""

        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    class TopicSignalInput(BaseModel):
        """Input model for the topic signal tool."""

        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

        topics: list[str] = Field(
            ...,
            description="Topics to probe, e.g. ['llm agents', 'rust']",
            min_length=1,
            max_length=25,
        )

    class RefreshInput(BaseModel):
        """Input model for the refresh tool."""

        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    _HAVE_PYDANTIC = True
except ImportError:  # pragma: no cover - pydantic always present in the project env
    ForecastInput = MoversInput = TopicSignalInput = RefreshInput = None  # type: ignore[assignment]
    _HAVE_PYDANTIC = False


# --- tools -------------------------------------------------------------------------


@tool(
    name="technews_forecast_categories",
    annotations={
        "title": "Forecast category trend",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def technews_forecast_categories(params: Any) -> str:
    """Forecast daily article counts per category over the horizon.

    Reads the daily_counts table (no backfill), builds the pandas frame,
    fits the TrendForecaster and predicts.

    Returns:
        str: JSON array of ``{"category", "date", "yhat"}``, or
        ``{"error": ..., "hint": ...}`` when data is missing.
    """
    horizon = params.horizon if params is not None else 7
    return json.dumps(forecast_core(horizon=horizon), indent=2, ensure_ascii=False)


@tool(
    name="technews_top_movers",
    annotations={
        "title": "Top category movers",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def technews_top_movers(params: Any) -> str:
    """Categories ranked by week-over-week pct change in article counts.

    Returns:
        str: JSON array of ``{"category", "pct_change"}``, or
        ``{"error": ..., "hint": ...}`` when data is missing.
    """
    del params
    return json.dumps(movers_core(), indent=2, ensure_ascii=False)


@tool(
    name="technews_search_topic_signal",
    annotations={
        "title": "Topic WebSearch signal",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def technews_search_topic_signal(params: Any) -> str:
    """Probe live WebSearch signal for the requested topics.

    Returns:
        str: JSON array of ``{"topic", "query", "hits", "top_titles",
        "source"}``, or ``{"error": ...}``.
    """
    topics = params.topics if params is not None else []
    return json.dumps(topic_signal_core(topics), indent=2, ensure_ascii=False)


@tool(
    name="technews_refresh_features",
    annotations={
        "title": "Backfill feature store",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def technews_refresh_features(params: Any) -> str:
    """Backfill the feature store daily counts from stored articles.

    Returns:
        str: JSON ``{"rows": <n>}`` or ``{"error": ...}``.
    """
    del params
    return json.dumps(refresh_core(), indent=2, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
