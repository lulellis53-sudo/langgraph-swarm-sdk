"""Build Google-dork queries: ``(A|B|C) AND (X|Y) site:… filetype:… after:YYYY-MM-DD``.

Pure string helpers, no network. Feed the result to any searcher as the query.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date

_FORBIDDEN = re.compile(r'["()|]')
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class DorkError(ValueError):
    """Raised when a term, operator value or date cannot form a valid dork."""


def _term(raw: str) -> str:
    text = raw.strip()
    if not text:
        raise DorkError("empty term")
    if _FORBIDDEN.search(text):
        raise DorkError(f"term may not contain quotes, parentheses or '|': {raw!r}")
    return f'"{text}"' if " " in text else text


def any_of(*terms: str) -> str:
    """Join *terms* into one OR group: ``(a|b|c)``.

    Terms containing spaces become exact phrases (``"two words"``).

    Args:
        *terms (str): One or more alternatives.

    Returns:
        str: Parenthesised group.

    Raises:
        DorkError: If there are no terms, or one is empty or contains ``"()|``.
    """
    if not terms:
        raise DorkError("any_of needs at least one term")
    return "(" + "|".join(_term(t) for t in terms) + ")"


def _iso(value: date | str, label: str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if not _ISO_DATE.fullmatch(value):
        raise DorkError(f"{label} must be YYYY-MM-DD, got {value!r}")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise DorkError(f"{label} is not a real date: {value!r}") from exc
    return value


def _operator(name: str, value: str) -> str:
    text = value.strip()
    if not text or any(c.isspace() or c in '"()|' for c in text):
        raise DorkError(f"{name}: needs one bare value, got {value!r}")
    return f"{name}:{text}"


def dork(
    *groups: str | Sequence[str],
    site: str | None = None,
    filetype: str | None = None,
    intitle: str | None = None,
    inurl: str | None = None,
    exclude: Iterable[str] = (),
    after: date | str | None = None,
    before: date | str | None = None,
) -> str:
    """Compose a dork: OR groups joined by ``AND``, then operators, then dates.

    Args:
        *groups (str | Sequence[str]): Each group is a list of alternatives
            (``["a", "b"]`` → ``(a|b)``) or a ready string / single term.
        site (str | None): ``site:`` restriction, e.g. ``github.com``.
        filetype (str | None): ``filetype:`` extension, e.g. ``pdf``.
        intitle (str | None): ``intitle:`` word.
        inurl (str | None): ``inurl:`` word.
        exclude (Iterable[str]): Terms to negate (``-term``).
        after (date | str | None): ``after:`` bound, ``date`` or ``YYYY-MM-DD``.
        before (date | str | None): ``before:`` bound, same format.

    Returns:
        str: Query string.

    Raises:
        DorkError: On no groups, bad terms, malformed dates, or ``after`` > ``before``.
    """
    if not groups:
        raise DorkError("dork needs at least one group")
    parts = [
        g
        if isinstance(g, str) and g.startswith("(")
        else any_of(*([g] if isinstance(g, str) else g))
        for g in groups
    ]
    parts_joined = " AND ".join(parts)
    ops = [
        _operator(name, value)
        for name, value in (
            ("site", site),
            ("filetype", filetype),
            ("intitle", intitle),
            ("inurl", inurl),
        )
        if value is not None
    ]
    ops += [f"-{_term(t)}" for t in exclude]
    lo = _iso(after, "after") if after is not None else None
    hi = _iso(before, "before") if before is not None else None
    if lo and hi and lo > hi:
        raise DorkError(f"after ({lo}) is later than before ({hi})")
    if lo:
        ops.append(f"after:{lo}")
    if hi:
        ops.append(f"before:{hi}")
    return " ".join([parts_joined, *ops])


__all__ = ["DorkError", "any_of", "dork"]
