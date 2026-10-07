"""Build Google-dork queries: ``(A|B|C) AND (X|Y) site:… filetype:… after:YYYY-MM-DD``.

Pure string helpers, no network. Feed the result to any searcher as the query.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
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


def _is_real_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return bool(_ISO_DATE.fullmatch(value))


def _phrase(raw: str) -> str:
    text = raw.strip()
    if not text or _FORBIDDEN.search(text):
        raise DorkError(f"exact phrase may not be empty or contain quotes/parentheses/'|': {raw!r}")
    return text


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
    intext: str | None = None,
    exact: Iterable[str] = (),
    exclude: Iterable[str] = (),
    exclude_sites: Iterable[str] = (),
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
        intext (str | None): ``intext:`` word.
        exact (Iterable[str]): Exact phrases, each ANDed in as ``"two words"``.
        exclude (Iterable[str]): Terms to negate (``-term``).
        exclude_sites (Iterable[str]): Hosts to negate (``-site:host``).
        after (date | str | None): ``after:`` bound, ``date`` or ``YYYY-MM-DD``.
        before (date | str | None): ``before:`` bound, same format.

    Returns:
        str: Query string.

    Raises:
        DorkError: On no groups, bad terms, malformed dates, or ``after`` > ``before``.
    """
    phrases = [f'"{_phrase(p)}"' for p in exact]
    if not groups and not phrases:
        raise DorkError("dork needs at least one group or exact phrase")
    parts = [
        g
        if isinstance(g, str) and g.startswith("(")
        else any_of(*([g] if isinstance(g, str) else g))
        for g in groups
    ]
    parts_joined = " AND ".join([*parts, *phrases])
    ops = [
        _operator(name, value)
        for name, value in (
            ("site", site),
            ("filetype", filetype),
            ("intitle", intitle),
            ("inurl", inurl),
            ("intext", intext),
        )
        if value is not None
    ]
    ops += [f"-{_operator('site', host)}" for host in exclude_sites]
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


_OPERATORS = ("site", "filetype", "intitle", "inurl", "intext", "after", "before")
_TOKEN = re.compile(r"-?(?:" + "|".join(_OPERATORS) + r'):(?:"[^"]+"|[^\s()|]+)|"[^"]+"|[^\s()|]+')


@dataclass(frozen=True, slots=True)
class DorkQuery:
    """A dork split into free text and operators (inverse of :func:`dork`).

    Attributes:
        terms: Free words and phrases (OR groups flattened, ``AND``/``OR`` dropped).
        sites: ``site:`` hosts.
        exclude_sites: ``-site:`` hosts.
        exclude_terms: ``-term`` words.
        filetype: ``filetype:`` extension.
        intitle: ``intitle:`` word.
        inurl: ``inurl:`` word.
        intext: ``intext:`` word.
        after: ``after:YYYY-MM-DD``.
        before: ``before:YYYY-MM-DD``.
    """

    terms: tuple[str, ...] = ()
    sites: tuple[str, ...] = ()
    exclude_sites: tuple[str, ...] = ()
    exclude_terms: tuple[str, ...] = ()
    filetype: str | None = None
    intitle: str | None = None
    inurl: str | None = None
    intext: str | None = None
    after: str | None = None
    before: str | None = None

    def plain(self) -> str:
        """Natural-language form for semantic APIs: terms plus operator values as words."""
        extras = [v for v in (self.intitle, self.intext, self.inurl, self.filetype) if v]
        return " ".join(dict.fromkeys([*self.terms, *extras]))


def parse_dork(query: str) -> DorkQuery:
    """Split a dork or plain query into :class:`DorkQuery` fields.

    Unknown ``word:value`` tokens and malformed ``after:``/``before:`` dates stay in
    ``terms`` instead of raising, so any user query is accepted.
    """
    terms: list[str] = []
    sites: list[str] = []
    ex_sites: list[str] = []
    ex_terms: list[str] = []
    ops: dict[str, str] = {}
    for token in _TOKEN.findall(query):
        negated = token.startswith("-")
        name, sep, value = token.lstrip("-").partition(":")
        value = value.strip('"')
        if sep and name in _OPERATORS and value:
            if name == "site":
                (ex_sites if negated else sites).append(value)
            elif name in {"after", "before"}:
                if _is_real_date(value) and not negated:
                    ops[name] = value
                else:
                    terms.append(token)
            elif not negated:
                ops[name] = value
            continue
        if token in {"AND", "OR"}:
            continue
        if negated and len(token) > 1:
            ex_terms.append(token[1:].strip('"'))
        else:
            terms.append(token.strip('"'))
    return DorkQuery(
        terms=tuple(dict.fromkeys(terms)),
        sites=tuple(sites),
        exclude_sites=tuple(ex_sites),
        exclude_terms=tuple(ex_terms),
        filetype=ops.get("filetype"),
        intitle=ops.get("intitle"),
        inurl=ops.get("inurl"),
        intext=ops.get("intext"),
        after=ops.get("after"),
        before=ops.get("before"),
    )


__all__ = ["DorkError", "DorkQuery", "any_of", "dork", "parse_dork"]
