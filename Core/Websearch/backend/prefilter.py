"""Regex prefilter for search hits before fusion."""

from __future__ import annotations

lazy import functools
lazy from collections.abc import Sequence
lazy from dataclasses import dataclass
lazy from urllib.parse import parse_qs, urlparse

lazy import regex as re
lazy from w3lib.url import url_query_cleaner

lazy from WebSearch.Core.frontend.websearchers import PrefilterPolicy, SearchHit


class RejectReason:
    """String rejection reasons."""

    bad_url = "bad_url"
    scheme = "scheme"
    blocked_domain = "blocked_domain"
    empty = "empty"
    short_snippet = "short_snippet"
    junk_snippet = "junk_snippet"
    wrong_language = "wrong_language"


_TRACKING_PARAMS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "yclid",
    "ttclid",
    "_ga",
    "ref",
    "ref_src",
    "ref_url",
    "spm",
    "scm",
    "spm_id_from",
    "vd_source",
)

_JUNK_SNIPPET = re.compile(
    r"(?i)\b("
    r"404\s+not\s+found|"
    r"access\s+denied|"
    r"enable\s+javascript\s+to\s+run|"
    r"please\s+enable\s+cookies|"
    r"cloudflare\s+ray\s+id|"
    r"verify\s+you\s+are\s+human|"
    r"captcha\s+verification|"
    r"security\s+check\s+to\s+access|"
    r"subscribe\s+to\s+(continue\s+reading|read\s+the\s+full\s+article)|"
    r"sign\s+in\s+to\s+continue"
    r")\b"
)


@functools.cache
def _langdetect_seeded() -> bool:
    """Import langdetect once and pin its RNG seed for deterministic results."""
    try:
        from langdetect import DetectorFactory
    except ImportError:
        return False
    DetectorFactory.seed = 0
    return True


def is_wrong_language(text: str, code: str) -> bool:
    """True when *text* is confidently not in language *code* (ISO 639-1).

    Uses langdetect (pure Python). Empty text, detection failures on short
    strings, or a missing install never reject: the gate is opt-in and
    fail-open so a missing extra cannot empty the result list.
    """
    if not text.strip() or not _langdetect_seeded():
        return False
    from langdetect import detect

    try:
        return detect(text) != code
    except Exception:  # noqa: BLE001 - short/noisy snippets raise LangDetectException
        return False


def clean_tracking_url(url: str) -> str:
    """Strip campaign tracking parameters from URL using w3lib."""
    try:
        return url_query_cleaner(url, parameterlist=_TRACKING_PARAMS, remove=True)
    except Exception:
        return url


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
    return len(parts) == 3 and parts[0] == "google" and len(parts[1]) == 2 and len(parts[2]) == 2


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
    hits: Sequence[SearchHit], policy: PrefilterPolicy
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
        url = clean_tracking_url(unwrap_redirect(hit.url))

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
        if policy.reject_junk and _JUNK_SNIPPET.search(snippet):
            rejected.append(Rejected(hit, RejectReason.junk_snippet))
            continue
        if policy.language and is_wrong_language(f"{title} {snippet}", policy.language):
            rejected.append(Rejected(hit, RejectReason.wrong_language))
            continue

        if policy.max_snippet_chars > 0 and len(snippet) > policy.max_snippet_chars:
            snippet = snippet[: policy.max_snippet_chars].rstrip() + "..."

        if url != hit.url or snippet != hit.snippet:
            kept.append(
                SearchHit(
                    title=hit.title,
                    url=url,
                    snippet=snippet,
                    searcher_id=hit.searcher_id,
                    also_from=hit.also_from,
                    api_tokens=hit.api_tokens,
                )
            )
        else:
            kept.append(hit)
    return kept, rejected
