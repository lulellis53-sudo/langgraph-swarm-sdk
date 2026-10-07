"""Offline tests for web-grounded evidence extraction and trend forecasting.

Fake backends only: no network, no API keys, no live WebSearch calls.
"""

from __future__ import annotations

from datetime import date

import pytest
from Prediction.web_evidence import (
    WebEvidenceError,
    collect_evidence,
    forecast_from_points,
    pair_dates_numbers,
    to_frame,
    web_forecast,
)
from WebSearch.frontend.websearchers import ProvidersConfig, SearcherSpec, SearchHit


def _hit(url: str, snippet: str, searcher: str = "fake") -> SearchHit:
    return SearchHit(title=url, url=url, snippet=snippet, searcher_id=searcher)


def test_pairs_iso_date_with_next_number() -> None:
    assert pair_dates_numbers("Price on 2026-10-01 was R$ 4200 in stores") == [
        (date(2026, 10, 1), 4200.0)
    ]


def test_parses_english_long_date() -> None:
    assert pair_dates_numbers("On March 5, 2026 it cost $1,234.56 shipped") == [
        (date(2026, 3, 5), 1234.56)
    ]


def test_parses_portuguese_date_and_decimal_comma() -> None:
    assert pair_dates_numbers("em 5 de março de 2026 por R$ 3.600,00 à vista") == [
        (date(2026, 3, 5), 3600.0)
    ]


def test_single_separator_with_three_digits_is_thousands() -> None:
    assert pair_dates_numbers("On 2026-09-30 listed at R$ 4.100")[0][1] == 4100.0
    assert pair_dates_numbers("On 2026-09-30 listed at 1,5 units")[0][1] == 1.5


def test_sentence_without_number_is_skipped() -> None:
    assert pair_dates_numbers(
        "On 2026-10-01 the card was out of stock. On 2026-10-02 it cost R$ 4.100"
    ) == [(date(2026, 10, 2), 4100.0)]


def test_gpu_model_numbers_are_skipped_for_prices() -> None:
    assert pair_dates_numbers("On 2026-10-01 the RTX 5060 cost R$ 2400") == [
        (date(2026, 10, 1), 2400.0)
    ]


def test_same_day_conflicts_take_median() -> None:
    points = collect_evidence(
        [
            _hit("https://a.example/", "On 2026-10-01 it cost R$ 4000"),
            _hit("https://b.example/", "Price 2026-10-01: R$ 4400 seen today"),
            _hit("https://c.example/", "On 2026-10-02 it cost R$ 3900"),
        ]
    )
    assert [p.date for p in points] == [date(2026, 10, 1), date(2026, 10, 2)]
    assert points[0].value == 4200.0  # median(4000, 4400)


def test_too_few_distinct_dates_raises() -> None:
    points = collect_evidence([_hit("https://a.example/", "On 2026-10-01 it cost R$ 4000")])
    with pytest.raises(WebEvidenceError, match="distinct"):
        forecast_from_points(points, horizon=7)


def test_trend_continues_and_band_covers() -> None:
    points = collect_evidence(
        [
            _hit("https://a.example/", "2026-10-01 price R$ 100"),
            _hit("https://b.example/", "2026-10-02 price R$ 110"),
            _hit("https://c.example/", "2026-10-03 price R$ 120"),
            _hit("https://d.example/", "2026-10-04 price R$ 130"),
        ]
    )
    out = forecast_from_points(points, horizon=3)
    assert len(out) == 3
    assert out[0].date == date(2026, 10, 5)
    assert out[0].value == pytest.approx(140.0, abs=1.0)
    assert out[0].low <= out[0].value <= out[0].high


def test_negative_predictions_clipped_to_zero() -> None:
    points = collect_evidence(
        [
            _hit("https://a.example/", "2026-10-01 price R$ 30"),
            _hit("https://b.example/", "2026-10-02 price R$ 20"),
            _hit("https://c.example/", "2026-10-03 price R$ 10"),
        ]
    )
    out = forecast_from_points(points, horizon=5)
    assert all(p.value >= 0 for p in out)
    assert out[-1].value == 0.0


def test_allow_negative_keeps_raw_trend() -> None:
    points = collect_evidence(
        [
            _hit("https://a.example/", "2026-10-01 price R$ 30"),
            _hit("https://b.example/", "2026-10-02 price R$ 20"),
            _hit("https://c.example/", "2026-10-03 price R$ 10"),
        ]
    )
    out = forecast_from_points(points, horizon=2, allow_negative=True)
    assert out[0].value == pytest.approx(0.0)
    assert out[1].value == pytest.approx(-10.0)


def test_to_frame_shape_matches_engine_input() -> None:
    points = collect_evidence(
        [
            _hit("https://a.example/", "2026-10-01 price R$ 100"),
            _hit("https://b.example/", "2026-10-02 price R$ 110"),
            _hit("https://c.example/", "2026-10-03 price R$ 120"),
        ]
    )
    out = forecast_from_points(points, horizon=4)
    frame = to_frame(out)
    assert list(frame.columns) == ["unique_id", "ds", "y"]
    assert len(frame) == 4
    assert (frame["unique_id"] == "web").all()


def test_web_forecast_fake_backend_end_to_end() -> None:
    config = ProvidersConfig(
        version=1,
        searchers=(SearcherSpec(id="fake", kind="websearcher", enabled=True),),
        extractor_order=("selectolax",),
    )

    def backend(query: str, spec: SearcherSpec) -> list[SearchHit]:
        del query, spec
        return [
            _hit("https://a.example/", "On 2026-10-01 the RTX 5060 cost R$ 2400"),
            _hit("https://b.example/", "On 2026-10-08 the RTX 5060 cost R$ 2380"),
            _hit("https://c.example/", "On 2026-10-15 the RTX 5060 cost R$ 2350"),
        ]

    result = web_forecast(
        "rtx 5060 price",
        config=config,
        backends={"fake": backend},
        horizon=7,
    )
    assert result.query == "rtx 5060 price"
    assert len(result.points) == 3
    assert len(result.predictions) == 7
    assert result.predictions[0].date == date(2026, 10, 16)
    assert result.predictions[0].value < 2350  # downtrend continues
    frame = result.to_frame()
    assert list(frame.columns) == ["unique_id", "ds", "y"]
