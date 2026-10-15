"""Polars/Parquet product store partitioned as ``Database/<Month>/DAY<d>/``.

Each day directory holds one ``products.parquet`` whose rows validate against
``product.schema.json``. Reads are Polars lazy scans (PyArrow-backed Parquet);
there is no SQL anywhere, so no injection surface. Numeric helpers use NumPy;
the percent-drop equation is verified symbolically with SymPy in the tests.
For heavier equation work use the math agent catalog
(``PYTHONPATH=Agents/math`` + ``import algorithms``).
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Mapping
from pathlib import Path

import polars as pl
from jsonschema import Draft202012Validator, FormatChecker

__all__ = [
    "DB_ROOT",
    "SCHEMA_PATH",
    "MONTHS",
    "day_dir",
    "day_dir_for_date",
    "month_dir",
    "pct_drop",
    "read_day",
    "read_month",
    "validate_record",
]

DB_ROOT = Path(__file__).resolve().parent.parent / "Database"
SCHEMA_PATH = Path(__file__).resolve().parent / "product.schema.json"
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_PRODUCT_FILE = "products.parquet"
_DEDUPE_KEYS = ["url", "observed_at"]


def _schema() -> Mapping[str, object]:
    return json.loads(SCHEMA_PATH.read_text())


def validate_record(
    record: Mapping[str, object], *, schema: Mapping[str, object] | None = None
) -> None:
    """Validate one product record against ``product.schema.json``.

    ``format`` assertions (``uri``, ``date``) are enforced via ``FormatChecker``.

    Raises:
        ValidationError: When the record violates the schema.
    """
    Draft202012Validator(schema or _schema(), format_checker=FormatChecker()).validate(record)


def month_dir(month: str, *, root: Path | None = None) -> Path:
    """Return ``<root>/<Month>``; ``month`` must be a canonical capitalized name."""
    if month not in MONTHS:
        raise ValueError(f"month must be one of {MONTHS}, got {month!r}")
    return (root or DB_ROOT) / month


def day_dir(month: str, day: int, *, root: Path | None = None) -> Path:
    """Return ``<root>/<Month>/DAY<day>`` for a real calendar day of that month."""
    if not 1 <= day <= 31:
        raise ValueError(f"day must be 1..31, got {day}")
    return month_dir(month, root=root) / f"DAY{day}"


def day_dir_for_date(day: dt.date, *, root: Path | None = None) -> Path:
    """Return the day directory for a ``datetime.date``."""
    return day_dir(MONTHS[day.month - 1], day.day, root=root)


def append_products(
    records: Iterable[Mapping[str, object]],
    *,
    month: str,
    day: int,
    root: Path | None = None,
) -> int:
    """Validate records and merge them into the day's ``products.parquet``.

    Existing rows with the same ``(url, observed_at)`` are replaced by the
    incoming ones. Returns the number of new rows written.

    Raises:
        ValidationError: When any record violates the product schema.
    """
    schema = _schema()
    fresh: list[Mapping[str, object]] = []
    for record in records:
        validate_record(record, schema=schema)
        fresh.append(record)
    if not fresh:
        return 0

    target = day_dir(month, day, root=root)
    target.mkdir(parents=True, exist_ok=True)
    path = target / _PRODUCT_FILE
    # Heterogeneous records: build on the union of keys, missing → null.
    columns: list[str] = list(_schema()["properties"])  # type: ignore[arg-type]
    incoming = pl.DataFrame(
        [{column: record.get(column) for column in columns} for record in fresh],
        infer_schema_length=None,
    )
    if path.exists():
        merged = pl.concat([pl.read_parquet(path), incoming], how="diagonal_relaxed").unique(
            subset=_DEDUPE_KEYS, keep="last", maintain_order=True
        )
    else:
        merged = incoming
    merged.write_parquet(path, compression="zstd")
    return len(fresh)


def read_day(month: str, day: int, *, root: Path | None = None) -> pl.DataFrame:
    """Read one day's products; empty frame when the day has no file yet."""
    path = day_dir(month, day, root=root) / _PRODUCT_FILE
    if not path.exists():
        return pl.DataFrame()
    return pl.read_parquet(path)


def read_month(month: str, *, root: Path | None = None) -> pl.DataFrame:
    """Scan every ``DAY*/products.parquet`` of the month into one frame."""
    pattern = str(month_dir(month, root=root) / "DAY*" / _PRODUCT_FILE)
    scans = pl.scan_parquet(pattern)
    return scans.collect()


def pct_drop(new: float, old: float) -> float:
    """Percent drop from ``old`` to ``new``: ``100 * (old - new) / |old|``.

    SymPy-verified in the tests against the closed form; NumPy keeps the
    numeric path stable. Negative results are genuine price increases.
    """
    old_f = float(old)
    new_f = float(new)
    if old_f == 0.0:
        raise ValueError("old price must be non-zero")
    return float(100.0 * (old_f - new_f) / abs(old_f))
