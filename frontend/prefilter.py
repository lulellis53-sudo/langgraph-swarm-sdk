"""Prefilter: drop unusable search hits before fusion can reward them."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from WebSearch.frontend.models import SearchHit
from WebSearch.frontend.providers import PrefilterPolicy

logger = logging.getLogger(__name__)

type RejectReason = Literal[
    "bad_url", "scheme", "blocked_domain", "empty", "short_snippet"
]

#: Google's own hosts (``google.com``, ``.de``, ``.co.uk``, ``.com.br``), never ``google.x.tld``.
_GOOGLE_HOST = re.compile(r"(www\.)?google\.(com?(\.[a-z]{2})?|[a-z]{2,3})")


@dataclass(frozen=True, slots=True)
class Rejected:
    """A hit dropped by :func:`prefilter_hits`, with the reason."""

    hit: SearchHit
    reason: RejectReason


def unwrap_redirect(url: str) -> str:
    """Return the target of a ``google.*/url?q=...`` tracking redirect.

    Args:
        url (str): Hit URL.

    Returns:
        str: The wrapped ``http(s)`` target, or *url* unchanged when it is not
        a recognised redirect or cannot be parsed.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    if parts.path != "/url" or not _GOOGLE_HOST.fullmatch(parts.hostname or ""):
        return url
    query = parse_qs(parts.query)
    for key in ("q", "url"):
        for target in query.get(key, []):
            if target.startswith(("http://", "https://")):
                return target
    return url


def _reject_reason(hit: SearchHit, policy: PrefilterPolicy) -> RejectReason | None:
    """Return why *hit* must be dropped, or ``None`` to keep it."""
    try:
        parts = urlsplit(hit.url.strip())
        host = parts.hostname
    except ValueError:
        return "bad_url"
    if not host:
        return "bad_url"
    if parts.scheme.lower() not in policy.schemes:
        return "scheme"
    host = host.rstrip(".")
    blocked = (domain.lower() for domain in policy.blocked_domains)
    if any(host == domain or host.endswith(f".{domain}") for domain in blocked):
        return "blocked_domain"
    title, snippet = hit.title.strip(), hit.snippet.strip()
    if (policy.require_title and not title) or not (title or snippet):
        return "empty"
    if len(snippet) < policy.min_snippet_chars:
        return "short_snippet"
    return None


def prefilter_hits(
    hits: Sequence[SearchHit], policy: PrefilterPolicy
) -> tuple[list[SearchHit], list[Rejected]]:
    """Unwrap tracking redirects, then drop hits the *policy* rejects.

    Checks run in this order and the first failure wins: unparsable URL,
    scheme outside the allowlist, blocked domain, empty title/snippet, short
    snippet. One bad hit never affects the others.

    Args:
        hits (Sequence[SearchHit]): Hits in rank order.
        policy (PrefilterPolicy): Limits to enforce.

    Returns:
        tuple[list[SearchHit], list[Rejected]]: Kept hits (rank order preserved,
        redirect URLs replaced by their targets) and the rejected hits with a reason.
    """
    kept: list[SearchHit] = []
    rejected: list[Rejected] = []
    for hit in hits:
        target = unwrap_redirect(hit.url)
        candidate = hit if target == hit.url else replace(hit, url=target)
        reason = _reject_reason(candidate, policy)
        if reason is None:
            kept.append(candidate)
        else:
            logger.debug("prefilter rejected %s: %s", hit.url, reason)
            rejected.append(Rejected(hit=hit, reason=reason))
    return kept, rejected


__all__ = ["RejectReason", "Rejected", "prefilter_hits", "unwrap_redirect"]
