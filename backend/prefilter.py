"""Regex prefilter for search hits before fusion."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from WebSearch.frontend.websearchers import PrefilterPolicy, SearchHit


class RejectReason:
    """String rejection reasons."""

    bad_url = "bad_url"
    scheme = "scheme"
    blocked_domain = "blocked_domain"
    empty = "empty"
    short_snippet = "short_snippet"


@dataclass(frozen=True, slots=True)
class Rejected:
    """A hit that failed prefiltering."""

    hit: SearchHit
    reason: str


def _domain(url: str) -> str | None:
    """Return lowercased netloc without leading www. or trailing dot."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if not parsed.netloc:
        return None
    host = parsed.netloc.lower().split(":", 1)[0]
    host = host.removeprefix("www.")
    while host.endswith("."):
        host = host[:-1]
    return host


def _is_google_host(host: str) -> bool:
    """Return True for google.com or ccTLD country hosts like google.co.uk."""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "google.com":
        return True
    parts = host.split(".")
    return (
        len(parts) == 3
        and parts[0] == "google"
        and len(parts[1]) == 2
        and len(parts[2]) == 2
    )


def unwrap_redirect(url: str) -> str:
    """Extract the target URL from a Google redirect link if present.

    Args:
        url: Candidate URL.

    Returns:
        str: Unwrapped target, or the original URL if not a Google redirect.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if parsed.path.rstrip("/") != "/url":
        return url
    if not _is_google_host(parsed.netloc):
        return url
    query = parse_qs(parsed.query)
    targets = query.get("q", [])
    if not targets:
        return url
    target = targets[0]
    if not target.startswith("http"):
        return url
    return target


def prefilter_hits(
    hits: list[SearchHit], policy: PrefilterPolicy
) -> tuple[list[SearchHit], list[Rejected]]:
    """Drop hits that fail scheme, domain, title, or snippet checks.

    Args:
        hits: Raw search hits.
        policy: Prefilter rules.

    Returns:
        tuple[list[SearchHit], list[Rejected]]: Kept hits and rejected records.
    """
    kept: list[SearchHit] = []
    rejected: list[Rejected] = []
    blocked = tuple(d.lower().removeprefix("www.") for d in policy.blocked_domains if d)
    for hit in hits:
        url = unwrap_redirect(hit.url)

        try:
            parsed = urlparse(url)
        except ValueError:
            rejected.append(Rejected(hit, RejectReason.bad_url))
            continue

        if not parsed.scheme or not parsed.netloc:
            rejected.append(Rejected(hit, RejectReason.bad_url))
            continue

        if parsed.scheme not in policy.schemes:
            rejected.append(Rejected(hit, RejectReason.scheme))
            continue

        domain = _domain(url)
        if domain is not None and any(
            domain == blocked_domain or domain.endswith(f".{blocked_domain}")
            for blocked_domain in blocked
        ):
            rejected.append(Rejected(hit, RejectReason.blocked_domain))
            continue

        title = hit.title.strip()
        snippet = hit.snippet.strip()
        if policy.require_title and not title:
            rejected.append(Rejected(hit, RejectReason.empty))
            continue
        if not title and not snippet:
            rejected.append(Rejected(hit, RejectReason.empty))
            continue
        if len(snippet) < policy.min_snippet_chars:
            rejected.append(Rejected(hit, RejectReason.short_snippet))
            continue

        if url != hit.url:
            kept.append(
                SearchHit(
                    title=hit.title,
                    url=url,
                    snippet=hit.snippet,
                    searcher_id=hit.searcher_id,
                )
            )
        else:
            kept.append(hit)
    return kept, rejected
