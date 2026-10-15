"""Web-grounded evidence: dated numbers from search results, then a trend.

Search hits are mined for sentences that pair a date with a number (prices,
counts). The resulting ``EvidencePoint`` series feeds a recency-weighted
linear trend with a ~80% band, and ``to_frame`` renders the forecast as a
long-format frame the offline :class:`Prediction.engine.ForecastEngine`
accepts. Network access is lazy: :func:`web_forecast` imports the vendored
``WebSearch`` package on first call.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

__all__ = [
    "EvidencePoint",
    "TrendPoint",
    "WebEvidenceError",
    "WebForecast",
    "collect_evidence",
    "forecast_from_points",
    "pair_dates_numbers",
    "to_frame",
    "web_forecast",
]

#: Band half-width multiplier: 1.28 sigma covers ~80% of a normal residual.
_BAND_Z = 1.28
#: Recency half-life in days for trend weights.
_HALF_LIFE_DAYS = 30.0

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

_DATE_PATTERNS = (
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b"),
    re.compile(
        rf"\b(?P<mon>{_MONTH_RE})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>\d{{4}})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?P<d>\d{{1,2}})\s+(?:de\s+)?(?P<mon>{_MONTH_RE})\.?,?\s*(?:de\s*)?(?P<y>\d{{4}})\b",
        re.IGNORECASE,
    ),
)
_NUMBER_RE = re.compile(r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+[.,]\d+|\d+")
#: Numbers right after these markers are product codes ("RTX 5060"), not values.
_MODEL_BEFORE_RE = re.compile(r"(?:rtx|gtx|radeon|rx|arc)\s*[a-z]*\s*$", re.IGNORECASE)
#: A number right after a currency symbol is the strongest value signal.
_CURRENCY_BEFORE_RE = re.compile(r"(?:r?\$|€)\s*$", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;!?])\s+|\n+")


class WebEvidenceError(ValueError):
    """Raised when search evidence is missing, unusable, or the tool is absent."""


@dataclass(frozen=True, slots=True)
class EvidencePoint:
    """One dated number mined from a search-result sentence."""

    date: date
    value: float
    url: str
    snippet: str


@dataclass(frozen=True, slots=True)
class TrendPoint:
    """One forecast step with its ~80% band."""

    date: date
    value: float
    low: float
    high: float


@dataclass(frozen=True, slots=True)
class WebForecast:
    """Evidence mined from one web query plus its trend projection."""

    query: str
    points: tuple[EvidencePoint, ...]
    predictions: tuple[TrendPoint, ...]

    def to_frame(self) -> pd.DataFrame:
        """Render the predictions as the engine's long-format input frame."""
        return to_frame(self.predictions)


def _parse_month(name: str) -> int:
    return _MONTHS[name.strip(". ").lower()]


def _match_date(sentence: str) -> tuple[date, int] | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.search(sentence)
        if match is None:
            continue
        parts = match.groupdict()
        if "mon" in parts:
            month = _parse_month(parts["mon"])
        else:
            month = int(parts["m"])
        day = int(parts["d"])
        year = int(parts["y"])
        try:
            return date(year, month, day), match.end()
        except ValueError:
            continue
    return None


def _parse_number(token: str) -> float:
    if "." in token and "," in token:
        thousand, decimal = (".", ",") if token.rfind(",") > token.rfind(".") else (",", ".")
    elif "," in token:
        thousand, decimal = (",", ".") if re.search(r",\d{3}(?:[.,]|$)", token) else (".", ",")
    elif "." in token:
        thousand, decimal = (".", "") if re.search(r"\.\d{3}(?:[.,]|$)", token) else ("", ".")
    else:
        thousand, decimal = "", ""
    cleaned = (
        token.replace(thousand, "").replace(decimal, ".")
        if decimal
        else token.replace(thousand, "")
    )
    return float(cleaned)


def _pick_value(sentence: str, start: int) -> float | None:
    """Choose the value number after a date: currency-anchored beats bare.

    Product codes ("RTX 5060") are skipped unless nothing else remains.
    """
    candidates = list(_NUMBER_RE.finditer(sentence, start))
    if not candidates:
        return None

    def prefix(match: re.Match[str]) -> str:
        return sentence[max(0, match.start() - 6) : match.start()]

    currency = [m for m in candidates if _CURRENCY_BEFORE_RE.search(prefix(m))]
    pool = currency or [m for m in candidates if not _MODEL_BEFORE_RE.search(prefix(m))]
    return _parse_number((pool or candidates)[0].group(0))


def pair_dates_numbers(text: str) -> list[tuple[date, float]]:
    """Pair the first date in each sentence with its best value number."""
    pairs: list[tuple[date, float]] = []
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        found = _match_date(sentence)
        if found is None:
            continue
        day, end = found
        value = _pick_value(sentence, end)
        if value is None:
            continue
        pairs.append((day, value))
    return pairs


def collect_evidence(hits: Iterable[Any]) -> tuple[EvidencePoint, ...]:
    """Turn search hits into one median-valued point per distinct date.

    Each hit needs ``url`` and ``snippet`` attributes (vendored
    ``WebSearch.frontend.websearchers.SearchHit`` qualifies).
    """
    by_date: dict[date, list[float]] = {}
    sources: dict[date, EvidencePoint] = {}
    for hit in hits:
        for day, value in pair_dates_numbers(getattr(hit, "snippet", "")):
            by_date.setdefault(day, []).append(value)
            sources.setdefault(day, EvidencePoint(day, value, str(getattr(hit, "url", "")), ""))
    points: list[EvidencePoint] = []
    for day in sorted(by_date):
        values = by_date[day]
        points.append(EvidencePoint(day, statistics.median(values), sources[day].url, ""))
    return tuple(points)


def _weighted_trend(points: Sequence[EvidencePoint]) -> tuple[float, float, float]:
    origin = points[0].date
    last = points[-1].date
    w_sum = wx_sum = wy_sum = wxx_sum = wxy_sum = 0.0
    samples: list[tuple[float, float, float]] = []
    for point in points:
        x = float((point.date - origin).days)
        age = (last - point.date).days
        weight = 0.5 ** (age / _HALF_LIFE_DAYS)
        w_sum += weight
        wx_sum += weight * x
        wy_sum += weight * point.value
        wxx_sum += weight * x * x
        wxy_sum += weight * x * point.value
        samples.append((weight, x, point.value))
    denom = w_sum * wxx_sum - wx_sum * wx_sum
    if denom == 0:
        raise WebEvidenceError("evidence spans a single day; no trend possible")
    slope = (w_sum * wxy_sum - wx_sum * wy_sum) / denom
    intercept = (wy_sum - slope * wx_sum) / w_sum
    sigma_sq = sum(w * (value - (intercept + slope * x)) ** 2 for w, x, value in samples) / w_sum
    return intercept, slope, sigma_sq**0.5


def forecast_from_points(
    points: Sequence[EvidencePoint],
    *,
    horizon: int,
    allow_negative: bool = False,
) -> tuple[TrendPoint, ...]:
    """Project the recency-weighted trend ``horizon`` days past the last point.

    Raises:
        WebEvidenceError: With fewer than 2 distinct dates or ``horizon < 1``.
    """
    if horizon < 1:
        raise WebEvidenceError("horizon must be >= 1")
    distinct = {point.date for point in points}
    if len(distinct) < 2:
        raise WebEvidenceError(f"need >= 2 distinct dated evidence points, got {len(distinct)}")
    ordered = sorted(points, key=lambda point: point.date)
    intercept, slope, sigma = _weighted_trend(ordered)
    origin = ordered[0].date
    last_day = (ordered[-1].date - origin).days

    def _clip(raw: float) -> float:
        return raw if allow_negative else max(raw, 0.0)

    steps: list[TrendPoint] = []
    for step in range(1, horizon + 1):
        x = float(last_day + step)
        value = intercept + slope * x
        steps.append(
            TrendPoint(
                date=ordered[-1].date + timedelta(days=step),
                value=_clip(value),
                low=_clip(value - _BAND_Z * sigma),
                high=_clip(value + _BAND_Z * sigma),
            )
        )
    return tuple(steps)


def to_frame(steps: Sequence[TrendPoint]) -> pd.DataFrame:
    """Render forecast steps as the engine's long-format input frame."""
    import pandas as pd

    return pd.DataFrame(
        {
            "unique_id": ["web"] * len(steps),
            "ds": [step.date for step in steps],
            "y": [step.value for step in steps],
        }
    )


def web_forecast(
    query: str,
    *,
    horizon: int = 7,
    limit: int = 10,
    config: Any | None = None,
    backends: Any | None = None,
    searcher_id: str | None = None,
    timeout_s: float = 30.0,
    allow_negative: bool = False,
) -> Any:
    """Search the web for ``query`` and forecast from the dated evidence found.

    ``config``/``backends``/``searcher_id`` pass through to the vendored
    ``WebSearch.agent_tools.search_hits``; offline callers inject fake
    ``backends``. Returns a ``WebForecast``-shaped dataclass with
    ``query``, ``points``, ``predictions`` and ``to_frame()``.

    Raises:
        WebEvidenceError: When the WebSearch package is missing or the hits
            carry too few dated numbers.
    """

    try:
        from WebSearch.agent_tools import search_hits
    except ImportError as exc:  # pragma: no cover - depends on vendored state
        raise WebEvidenceError(
            "WebSearch package not vendored in this lane; restore with: "
            "git -C ~/Swarm archive keep/websearch-package-02ec1de WebSearch "
            "| tar -x -C ~/Swarm-Prediction"
        ) from exc

    hits = search_hits(
        query,
        limit=limit,
        config=config,
        backends=backends,
        searcher_id=searcher_id,
        timeout_s=timeout_s,
    )
    points = collect_evidence(hits)
    predictions = forecast_from_points(points, horizon=horizon, allow_negative=allow_negative)
    return WebForecast(query=query, points=points, predictions=predictions)
