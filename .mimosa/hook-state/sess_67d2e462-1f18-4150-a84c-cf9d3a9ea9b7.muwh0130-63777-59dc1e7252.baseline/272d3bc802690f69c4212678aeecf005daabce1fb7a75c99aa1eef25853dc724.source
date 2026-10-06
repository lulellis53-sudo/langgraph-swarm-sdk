"""Dated numeric evidence extraction and same-day conflict resolution."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

__all__ = ["EvidencePoint", "dedupe_by_date", "pair_dates_numbers"]

#: Sentence-splitting keeps date/number pairing local.
_SENTENCE = re.compile(r"[.!?]\s+")
_ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_MONTHS = {
    "january": 1,
    "janeiro": 1,
    "february": 2,
    "fevereiro": 2,
    "march": 3,
    "marco": 3,
    "março": 3,
    "april": 4,
    "abril": 4,
    "may": 5,
    "maio": 5,
    "june": 6,
    "junho": 6,
    "july": 7,
    "julho": 7,
    "august": 8,
    "agosto": 8,
    "september": 9,
    "setembro": 9,
    "october": 10,
    "outubro": 10,
    "november": 11,
    "novembro": 11,
    "december": 12,
    "dezembro": 12,
}
_TEXT_DATE = re.compile(
    r"\b(\d{1,2})\s+(?:de\s+)?(" + "|".join(_MONTHS) + r")\s+(?:de\s+)?(20\d{2})\b"
    r"|\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),?\s+(20\d{2})\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")

#: Context window kept around a date when building a snippet.
_SNIPPET_CONTEXT = 40
_SNIPPET_MAX = 80


@dataclass(frozen=True, slots=True)
class EvidencePoint:
    """One dated numeric observation extracted from a searched document."""

    date: date
    value: float
    source_url: str
    snippet: str


_ANY_DATE = re.compile(_ISO_DATE.pattern + "|" + _TEXT_DATE.pattern, re.IGNORECASE)
#: PT-BR style numbers: dot thousands, comma decimals ("14.499", "13.999,90").
_NUMBER_COMMA = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?")

# Combined-pattern group layout (groups() is 0-based here): tuple[0:3] ISO
# (year, month, day); tuple[3:6] textual day-first (day, month, year);
# tuple[6:9] textual month-first (month, day, year).
_ISO_GROUPS = slice(0, 3)
_DAY_FIRST_GROUPS = slice(3, 6)
_MONTH_FIRST_GROUPS = slice(6, 9)


#: How far a ``require_near`` token may sit from a (date, number) pair.
_NEAR_CONTEXT = 150


def pair_dates_numbers(
    text: str,
    *,
    decimal_comma: bool = False,
    require_near: Sequence[str] = (),
) -> list[tuple[date, float]]:
    """Extract ``(date, number)`` pairs from normalized text.

    Free mode (no ``require_near``): each date pairs with the first number
    between it and the next date, so a sentence carrying several dated prices
    yields several pairs.

    Scoped mode (``require_near`` set): dates pair only with numbers in the
    **same sentence**, the number may not itself be one of the tokens (a model
    id is not a price), and the sentence must contain every token. This drops
    pairs that belong to other entities on a busy page (e.g. another GPU
    model's price).

    Args:
        text: Normalized document text.
        decimal_comma: Parse numbers with dot thousands and comma decimals
            (``"14.499"`` -> 14499.0), the PT-BR convention.
        require_near: Casefolded entity tokens scoping the pairing.

    Returns:
        Pairs in document order; undated numbers and unparseable dates are skipped.
    """
    needles = tuple(token.casefold() for token in require_near)
    number_pattern = _NUMBER_COMMA if decimal_comma else _NUMBER
    pairs: list[tuple[date, float]] = []
    for date_match in _ANY_DATE.finditer(text):
        try:
            point_date = _parse_date(date_match)
        except ValueError:
            continue
        if needles:
            best = _scoped_numbers(
                text, date_match, needles, number_pattern, decimal_comma=decimal_comma
            )
            if best is not None:
                pairs.append((point_date, best))
        else:
            window_end = _next_date_start(text, date_match)
            number_match = number_pattern.search(text, date_match.end(), window_end)
            if number_match is not None:
                pairs.append(
                    (point_date, _to_float(number_match.group(0), decimal_comma=decimal_comma))
                )
    return pairs


def _next_date_start(text: str, date_match: re.Match[str]) -> int:
    """Return the start of the next date after ``date_match``, or text length."""
    following = _ANY_DATE.search(text, date_match.end())
    return following.start() if following else len(text)


def _scoped_numbers(
    text: str,
    date_match: re.Match[str],
    needles: tuple[str, ...],
    number_pattern: re.Pattern[str],
    *,
    decimal_comma: bool,
) -> float | None:
    """Return the nearest needle-scoped price for one date, or ``None``.

    The window is the sentence containing the date (expanded to cover numbers
    that precede the date, as in ``"caiu para R$ 3.499 em 20 de setembro"``).
    Numbers inside the matched date itself (its day and year) are skipped, as
    are numbers equal to one of the needle tokens (a model id is not a price).
    """
    sentence_start = max(
        (boundary.end() for boundary in _SENTENCE.finditer(text, 0, date_match.start())),
        default=0,
    )
    following = _SENTENCE.search(text, date_match.end())
    sentence_end = following.end() if following else len(text)
    for number_match in number_pattern.finditer(text, sentence_start, sentence_end):
        if number_match.start() < date_match.end() and number_match.end() > date_match.start():
            continue
        token = number_match.group(0)
        if token.casefold() in needles:
            continue
        near = text[max(sentence_start, number_match.start() - _NEAR_CONTEXT) : number_match.end()]
        near_cf = near.casefold()
        if all(needle in near_cf for needle in needles):
            return _to_float(token, decimal_comma=decimal_comma)
    return None


def _to_float(token: str, *, decimal_comma: bool) -> float:
    """Parse one number token under the selected decimal convention."""
    if decimal_comma:
        return float(token.replace(".", "").replace(",", "."))
    return float(token.replace(",", ""))


def _parse_date(match: re.Match[str]) -> date:
    """Parse one ISO or textual date regex match (English or Portuguese)."""
    if match.group(1) is not None:  # ISO "2026-08-12"
        year, month, day = (int(part) for part in match.groups()[_ISO_GROUPS])
        return date(year, month, day)
    if match.group(5) is not None:  # "05 October 2026" / "05 de outubro de 2026"
        day, month_name, year = int(match.group(4)), match.group(5), int(match.group(6))
    else:  # "October 05, 2026"
        month_name, day, year = match.group(7), int(match.group(8)), int(match.group(9))
    return date(year, _MONTHS[month_name.lower()], day)


def evidence_snippet(text: str, point_date: date) -> str:
    """Return a bounded context window around the first mention of the date's year."""
    start = max(0, text.find(str(point_date.year)) - _SNIPPET_CONTEXT)
    return text[start:][:_SNIPPET_MAX]


def dedupe_by_date(points: list[EvidencePoint], warnings: list[str]) -> list[EvidencePoint]:
    """Keep one point per date: the median when several documents disagree.

    Args:
        points: Evidence points in any order.
        warnings: List to append conflict notices to.

    Returns:
        Points sorted by date, one per distinct date.
    """
    by_date: dict[date, list[EvidencePoint]] = {}
    for point in points:
        by_date.setdefault(point.date, []).append(point)
    unique: list[EvidencePoint] = []
    for point_date in sorted(by_date):
        same_day = by_date[point_date]
        if len(same_day) > 1:
            values = sorted(item.value for item in same_day)
            middle = len(values) // 2
            median = (
                values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
            )
            keeper = min(same_day, key=lambda item: abs(item.value - median))
            warnings.append(
                f"{len(same_day)} conflicting values on "
                f"{point_date.isoformat()}; kept the median one"
            )
            unique.append(EvidencePoint(point_date, median, keeper.source_url, keeper.snippet))
        else:
            unique.append(same_day[0])
    return unique
