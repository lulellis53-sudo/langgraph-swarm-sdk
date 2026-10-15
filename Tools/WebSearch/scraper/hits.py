"""Hit cleanup for WebScraper: normalize, score, and prune snippets for agents.

Stdlib only. Token packing lives in :mod:`WebSearch.scraper.tokensaver`; this module
makes each hit cheaper before the packer runs.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from WebSearch.scraper.tokensaver import PackResult, pack_hits, savings_report

__all__ = [
    "as_agent_dict",
    "canonicalize_url",
    "compact_hits",
    "format_brief",
    "from_searxng",
    "from_semantic_chunk",
    "hit_score",
    "prepare_hits",
    "prune_snippet_to_query",
]

_SEPARATOR = re.compile(r"\s+[|–—·-]\s+")
_NON_ALNUM = re.compile(r"[\W_]+", re.UNICODE)
_TOKEN = re.compile(r"\w+", re.UNICODE)
_WS = re.compile(r"\s+")
_TRACKING = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
    }
)
_STOP = frozenset(
    (
        "a an and are as at be by for from how in is it of on or that the to was what with "
        "o os as de da do das dos em um uma uns umas para com sem por nao não e ou se que "
        "ao aos na nas no nos"
    ).split()
)


def canonicalize_url(url: str) -> str:
    """Drop tracking params, fragments, and a trailing slash; lowercase the host."""
    raw = url.strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    if not parts.scheme or not (parts.netloc or parts.hostname):
        return raw.rstrip("/")
    host = (parts.hostname or "").removeprefix("www.").lower()
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING
        ]
    )
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    netloc = host
    if parts.port:
        netloc = f"{host}:{parts.port}"
    if parts.username:
        user = parts.username
        if parts.password:
            user = f"{user}:{parts.password}"
        netloc = f"{user}@{netloc}"
    return urlunsplit((parts.scheme.lower() or "https", netloc, path, query, ""))


def _alnum(text: str) -> str:
    return _NON_ALNUM.sub("", text.casefold())


def _site_keys(url: str) -> set[str]:
    try:
        host = (urlsplit(url).hostname or "").removeprefix("www.")
    except ValueError:
        return set()
    keys = {_alnum(label) for label in host.split(".")[:-1]}
    keys.add(_alnum(host))
    keys.discard("")
    return keys


def _strip_site_suffix(title: str, url: str) -> str:
    matches = list(_SEPARATOR.finditer(title))
    if not matches:
        return title
    last = matches[-1]
    head, tail = title[: last.start()].rstrip(), title[last.end() :]
    return head if head and _alnum(tail) in _site_keys(url) else title


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def query_terms(query: str) -> set[str]:
    """Distinct query tokens that carry ranking signal (PT/EN stopwords dropped)."""
    return {t for t in _TOKEN.findall(query.casefold()) if len(t) > 1 and t not in _STOP}


def prune_snippet_to_query(snippet: str, query: str, max_chars: int = 320) -> str:
    """Keep the sentence windows that mention query terms, up to ``max_chars``.

    Runs on short snippets too (not only over-budget ones): a trailing
    marketing/boilerplate sentence that shares no query term is dropped, so
    shared tails like "oferta valida hoje, frete gratis…" never reach the packer.
    """
    text = _clean(snippet)
    if not text:
        return text
    terms = query_terms(query)
    if not terms:
        return text[:max_chars].rstrip() + "..."
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    if not parts:
        return text[:max_chars].rstrip() + "..."
    scored = sorted(
        ((set(_TOKEN.findall(part.casefold())) & terms, part) for part in parts),
        key=lambda row: len(row[0]),
        reverse=True,
    )
    selected: list[str] = []
    covered: set[str] = set()
    total = 0
    for new_terms, part in scored:
        # Keep only sentences that add a query term not already covered; a
        # trailing marketing tail repeats terms the topic sentence already hit.
        if selected and not (new_terms - covered):
            continue
        extra = len(part) + (1 if selected else 0)
        if total + extra <= max_chars:
            selected.append(part)
            covered |= new_terms
            total += extra
        elif not selected:
            selected.append(part[:max_chars].rstrip() + "...")
            covered |= new_terms
            break
    if not selected:
        return text[:max_chars].rstrip() + "..."
    order = {part: i for i, part in enumerate(parts)}
    selected.sort(key=lambda part: order.get(part, 0))
    result = " ".join(selected)
    return result if len(result) <= max_chars else result[:max_chars].rstrip() + "..."


def hit_score(title: str, snippet: str, query: str) -> float:
    """Share of distinct query terms found in title or snippet (0..1)."""
    terms = query_terms(query)
    if not terms:
        return 0.0
    haystack = set(_TOKEN.findall(f"{title} {snippet}".casefold()))
    return len(terms & haystack) / len(terms)


def _snippet_of(raw: dict[str, Any]) -> str:
    for key in ("snippet", "content", "text"):
        value = raw.get(key)
        if value:
            return str(value)
    return ""


def as_agent_dict(hit: dict[str, Any]) -> dict[str, Any]:
    """Stable agent hit schema: title, url, snippet, score, source."""
    return {
        "title": str(hit.get("title") or ""),
        "url": str(hit.get("url") or ""),
        "snippet": str(hit.get("snippet") or hit.get("content") or ""),
        "score": float(hit.get("score") or 0.0),
        "source": str(hit.get("source") or "searxng"),
    }


def from_searxng(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map a SearXNG ``results`` list into the agent hit schema."""
    return [
        {
            "title": row.get("title", ""),
            "url": row.get("url", ""),
            "snippet": row.get("content", "") or row.get("snippet", ""),
            "source": row.get("engine") or row.get("source") or "searxng",
        }
        for row in rows
    ]


def from_semantic_chunk(url: str, idx: int, text: str, score: float) -> dict[str, Any]:
    """One pgvector chunk as a hit dict."""
    return {
        "title": f"{url}#{idx}",
        "url": url,
        "snippet": text,
        "score": float(score),
        "chunk_idx": int(idx),
        "source": "pgvector",
    }


def prepare_hits(
    raw: list[dict[str, Any]],
    query: str,
    *,
    snippet_chars: int = 320,
) -> list[dict[str, Any]]:
    """Canonicalize URLs, strip site suffixes, prune snippets, and score hits."""
    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        url = canonicalize_url(str(item.get("url", "")))
        if not url or url in seen:
            continue
        title = _strip_site_suffix(_clean(str(item.get("title", "") or url)), url)
        snippet = prune_snippet_to_query(_snippet_of(item), query, max_chars=snippet_chars)
        if not title and not snippet:
            continue
        seen.add(url)
        score = item.get("score")
        lexical = hit_score(title, snippet, query)
        prepared.append(
            {
                "title": title or url,
                "url": url,
                "snippet": snippet,
                "score": float(score) if score is not None else lexical,
                "lexical": lexical,
                "source": str(item.get("source") or item.get("engine") or "searxng"),
            }
        )
    return prepared


def compact_hits(
    raw: list[dict[str, Any]],
    query: str,
    *,
    budget_tokens: int = 400,
    min_score: float | None = None,
    limit: int = 10,
    snippet_chars: int = 320,
) -> PackResult:
    """Prepare hits then pack them into ``budget_tokens`` for an agent prompt."""
    prepared = prepare_hits(raw, query, snippet_chars=snippet_chars)
    score_key = "lexical" if min_score is not None else "score"
    result = pack_hits(
        prepared,
        budget_tokens,
        text_key="snippet",
        url_key="url",
        score_key=score_key,
        min_score=min_score,
        on_oversized="truncate",
    )
    if len(result.kept) > limit:
        overflow = result.kept[limit:]
        result.kept = result.kept[:limit]
        result.dropped.extend({**hit, "_drop_reason": "limit"} for hit in overflow)
    return result


def format_brief(result: PackResult, original_count: int) -> str:
    """Render packed hits as ``[title](url)`` blocks plus a savings footer."""
    if not result.kept:
        return "No results found."
    body = "\n\n".join(
        f"[{hit.get('title', hit.get('url', ''))}]({hit.get('url', '')})\n{hit.get('snippet', '')}"
        for hit in result.kept
    )
    return f"{body}\n\n({savings_report(result, original_count)})"
