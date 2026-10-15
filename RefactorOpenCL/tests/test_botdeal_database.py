"""Tests for the BotDeal Polars product store and discovery dorks.

Run from ~/BotDeal with the lane venv:

    PYTHONPATH="$HOME/BotDeal:$HOME/Swarm-Prediction" \\
      ~/Swarm-Prediction/.venv/bin/python -m pytest tests/test_botdeal_database.py -q
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from jsonschema import ValidationError
from Prediction.BotDeal.database import (
    day_dir,
    month_dir,
    pct_drop,
    read_day,
    read_month,
    validate_record,
)


def _record(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "unique_id": "rtx-5090",
        "name": "Placa RTX 5090",
        "source": "lista.mercadolivre.com.br",
        "url": "https://lista.mercadolivre.com.br/rtx-5090",
        "observed_at": "2026-10-06",
    }
    base.update(overrides)
    return base


def test_day_dir_validates_month_and_day() -> None:
    assert day_dir("September", 30).name == "DAY30"
    assert month_dir("October").name == "October"
    with pytest.raises(ValueError, match="month"):
        month_dir("september")
    with pytest.raises(ValueError, match="day"):
        day_dir("September", 0)
    with pytest.raises(ValueError, match="day"):
        day_dir("September", 32)


def test_day_dir_for_date_maps_calendar() -> None:
    from Prediction.BotDeal.database import day_dir_for_date

    assert day_dir_for_date(dt.date(2026, 9, 5)).name == "DAY5"
    assert day_dir_for_date(dt.date(2026, 10, 31)).name == "DAY31"


def test_append_dedupe_and_month_scan(tmp_path: Path) -> None:
    first = _record()
    again = _record(price=21000.0, currency="BRL")
    written = 0
    for record in (first, again):
        written += append_count(record, tmp_path)
    assert written == 2

    day_frame = read_day("September", 6, root=tmp_path)
    assert len(day_frame) == 1  # same (url, observed_at) → replaced, not duplicated
    assert day_frame["price"][0] == 21000.0

    day_dir("September", 7, root=tmp_path)
    from Prediction.BotDeal.database import append_products

    append_products(
        [_record(url="https://a.example/x", observed_at="2026-09-07")],
        month="September",
        day=7,
        root=tmp_path,
    )
    month_frame = read_month("September", root=tmp_path)
    assert len(month_frame) == 2


def append_count(record: dict[str, object], root: Path) -> int:
    from Prediction.BotDeal.database import append_products

    return append_products([record], month="September", day=6, root=root)


def test_append_validates_against_schema(tmp_path: Path) -> None:
    from Prediction.BotDeal.database import append_products

    with pytest.raises(ValidationError):
        append_products([_record(url="not-a-uri")], month="September", day=1, root=tmp_path)
    with pytest.raises(ValidationError):
        append_products([_record(extra="nope")], month="September", day=1, root=tmp_path)


def test_validate_record_accepts_minimal() -> None:
    validate_record(_record())


def test_pct_drop_matches_sympy_closed_form() -> None:
    pytest.importorskip("sympy")
    import sympy

    old, new = sympy.symbols("old new", real=True)
    closed_form = sympy.simplify(100 * (old - new) / old)
    example = closed_form.subs({old: 2400, new: 1800})
    assert float(example) == pct_drop(1800.0, 2400.0) == 25.0
    assert pct_drop(2500.0, 2000.0) == -25.0  # negative → price increase
    with pytest.raises(ValueError, match="non-zero"):
        pct_drop(100.0, 0.0)
