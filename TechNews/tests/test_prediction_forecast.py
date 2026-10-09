"""Offline tests for technews.prediction.forecast.TrendForecaster."""

from __future__ import annotations

import pandas as pd
import pytest

from technews.prediction.forecast import ForecastPoint, TrendForecaster


def make_frame(n_days: int = 21) -> pd.DataFrame:
    dates = pd.date_range("2026-09-01", periods=n_days, freq="D")
    return pd.concat(
        [
            pd.DataFrame(
                {
                    "unique_id": "ai",
                    "ds": dates,
                    "y": range(10, 10 + n_days),  # rising trend
                }
            ),
            pd.DataFrame(
                {
                    "unique_id": "hardware",
                    "ds": dates,
                    "y": range(50, 50 - n_days, -1),  # falling trend
                }
            ),
        ],
        ignore_index=True,
    )


def test_fit_predict_shapes() -> None:
    fc = TrendForecaster(horizon=7)
    assert not fc.is_fitted
    with pytest.raises(RuntimeError):
        fc.predict()
    fc.fit(make_frame())
    assert fc.is_fitted
    points = fc.predict()
    assert len(points) == 14  # 2 series x 7 days
    assert all(isinstance(p, ForecastPoint) for p in points)
    assert points == sorted(points, key=lambda p: (p.category, p.date))
    cats = {p.category for p in points}
    assert cats == {"ai", "hardware"}
    from datetime import date as _date

    for p in points:
        _date.fromisoformat(p.date)  # ISO date
        assert isinstance(p.yhat, float)


def test_movers_ordering() -> None:
    fc = TrendForecaster(horizon=7)
    fc.fit(make_frame())
    movers = fc.movers(make_frame())
    assert {c for c, _ in movers} == {"ai", "hardware"}
    # sorted by abs change, descending
    abs_vals = [abs(v) for _, v in movers]
    assert abs_vals == sorted(abs_vals, reverse=True)
    # rising series must not rank below falling one
    assert dict(movers)["ai"] >= dict(movers)["hardware"]


def test_movers_skips_zero_history() -> None:
    frame = make_frame()
    frame.loc[frame["unique_id"] == "hardware", "y"] = 0
    fc = TrendForecaster(horizon=7)
    fc.fit(frame)
    movers = fc.movers(frame)
    assert [c for c, _ in movers] == ["ai"]


def test_fit_rejects_bad_input() -> None:
    fc = TrendForecaster(horizon=3)
    with pytest.raises(ValueError, match="missing columns"):
        fc.fit(pd.DataFrame({"a": [1]}))
    with pytest.raises(ValueError, match="rows per series"):
        fc.fit(make_frame(n_days=5))
    with pytest.raises(ValueError):
        TrendForecaster(horizon=0)


def test_linear_fallback_directly() -> None:
    fc = TrendForecaster(horizon=7)
    frame = make_frame()
    fc._fit_fallback(frame)
    pts = fc._linear_fallback_predict("ai", 7)
    assert len(pts) == 7
    assert pts[0].category == "ai"
    # slope 1/day: day after last (y=30) should be 31
    assert pts[0].yhat == pytest.approx(31.0)
    assert pts[6].yhat == pytest.approx(37.0)
    # dates continue after the last observed day
    assert pts[0].date == "2026-09-22"
    assert pts[6].date == "2026-09-28"


def test_fallback_via_missing_import(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name.split(".")[0] in {"lightgbm", "mlforecast"}:
            raise ImportError(f"no module named {name!r}")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fake_import)
    fc = TrendForecaster(horizon=5)
    fc.fit(make_frame())
    pts = fc.predict()
    assert len(pts) == 10  # fallback still forecasts all series
    assert fc._used_fallback
