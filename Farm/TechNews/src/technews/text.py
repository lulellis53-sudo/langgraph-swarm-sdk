"""Pure text helpers: URL canonicalization, excerpts, hashing."""

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from selectolax.lexbor import LexborHTMLParser

EXCERPT_LIMIT = 300
_ELLIPSIS = "…"
_WS = re.compile(r"\s+")


def canonical_url(url: str) -> str:
    """Return a stable form of ``url`` for deduplication.

    Lowercases scheme and host, drops the fragment and ``utm_*`` parameters, sorts the
    remaining query keys and removes a trailing slash from non-root paths.
    """
    parts = urlsplit(url.strip())
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
    )
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def make_excerpt(raw: str, limit: int = EXCERPT_LIMIT) -> str:
    """Return plain text from ``raw`` HTML, at most ``limit`` characters.

    Truncation happens at a word boundary when one exists, and ends with an ellipsis.
    """
    if not raw:
        return ""
    tree = LexborHTMLParser(raw)
    for node in tree.css("script, style"):
        node.decompose()
    text = _WS.sub(" ", tree.text(separator=" ")).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > 0:
        cut = cut[:space]
    return cut.rstrip() + _ELLIPSIS


def content_hash(title: str, excerpt: str) -> str:
    """Return a SHA-256 hex digest of the normalized title and excerpt."""
    norm = _WS.sub(" ", f"{title}\n{excerpt}").strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()
