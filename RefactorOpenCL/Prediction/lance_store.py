"""Optional LanceDB persistence for ``ForecastEngine`` prediction runs.

Install with ``uv sync --extra forecast-lancedb``. Remote URIs may use the env var
named by ``api_key_env`` (default ``LANCEDB_API_KEY``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from Prediction.engine import ForecastError

if TYPE_CHECKING:
    import pandas as pd

__all__ = ["ForecastRecord", "LanceForecastStore"]


@dataclass(frozen=True, slots=True)
class ForecastRecord:
    """Metadata for one appended forecast run."""

    run_id: str
    table_name: str
    created_at: str
    row_count: int


def _table_name(run_id: str) -> str:
    return f"forecast_{run_id}"


def _read_table_head(table: Any, limit: int) -> pd.DataFrame:
    import pandas as pd

    if hasattr(table, "head"):
        return table.head(limit).to_pandas()
    frame = table.to_pandas()
    if not isinstance(frame, pd.DataFrame):
        raise ForecastError("LanceDB table did not return a pandas DataFrame")
    return frame.head(limit)


class LanceForecastStore:
    """Append immutable forecast runs and read bounded slices by ``run_id``."""

    def __init__(self, uri: str, *, api_key_env: str = "LANCEDB_API_KEY") -> None:
        if not uri.strip():
            raise ForecastError("uri must be a non-empty LanceDB path or URI")
        self._uri = uri
        self._api_key_env = api_key_env
        self._db: Any = None

    def _connect(self) -> Any:
        if self._db is not None:
            return self._db
        try:
            import lancedb
        except ImportError as exc:
            raise ForecastError(
                "LanceDB is not installed; run uv sync --extra forecast-lancedb"
            ) from exc
        kwargs: dict[str, Any] = {}
        api_key = os.environ.get(self._api_key_env)
        if api_key:
            kwargs["api_key"] = api_key
        self._db = lancedb.connect(self._uri, **kwargs)
        return self._db

    @staticmethod
    def _list_tables(db: Any) -> set[str]:
        if hasattr(db, "table_names"):
            return set(db.table_names())
        if hasattr(db, "list_tables"):
            listed = db.list_tables()
            if isinstance(listed, dict) and "tables" in listed:
                return {row["name"] for row in listed["tables"]}
            return set(listed)
        raise ForecastError("LanceDB connection has no table listing API")

    def append_forecasts(self, forecasts: pd.DataFrame) -> str:
        """Persist one forecast frame under a new ``run_id``; never overwrites."""
        import pandas as pd

        if not isinstance(forecasts, pd.DataFrame):
            raise ForecastError("forecasts must be a pandas DataFrame")
        if forecasts.empty:
            raise ForecastError("forecasts must not be empty")
        missing = [col for col in ("unique_id", "ds") if col not in forecasts.columns]
        if missing:
            raise ForecastError(f"forecast frame missing columns: {missing}")

        run_id = uuid4().hex
        name = _table_name(run_id)
        db = self._connect()
        if name in self._list_tables(db):
            raise ForecastError(f"run table already exists: {name}")

        created_at = datetime.now(UTC).isoformat()
        payload = forecasts.copy()
        payload["run_id"] = run_id
        payload["created_at"] = created_at
        db.create_table(name, payload)
        return run_id

    def describe_run(self, run_id: str) -> ForecastRecord:
        """Return row count and table metadata for ``run_id``."""
        db = self._connect()
        name = _table_name(run_id)
        if name not in self._list_tables(db):
            raise ForecastError(f"unknown run_id: {run_id}")
        table = db.open_table(name)
        preview = _read_table_head(table, 1)
        row_count = int(getattr(table, "count_rows", lambda: len(table.to_pandas()))())
        sample = preview
        created_at = str(sample["created_at"].iloc[0]) if "created_at" in sample.columns else ""
        return ForecastRecord(
            run_id=run_id,
            table_name=name,
            created_at=created_at,
            row_count=row_count,
        )

    def read_run(self, run_id: str, *, limit: int = 500) -> pd.DataFrame:
        """Load up to ``limit`` rows for ``run_id``."""
        if limit < 1:
            raise ForecastError("limit must be >= 1")
        db = self._connect()
        name = _table_name(run_id)
        if name not in self._list_tables(db):
            raise ForecastError(f"unknown run_id: {run_id}")
        table = db.open_table(name)
        return _read_table_head(table, limit)
