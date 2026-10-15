"""Text and URL normalization applied after every extractor."""

from __future__ import annotations

import html as html_lib
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import regex as re

_WHITESPACE = re.compile(r"\s+")
_INVISIBLE = re.compile(r"(?![\u200c\u200d])[\p{Cf}\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
#: Separator/ornament lines: punctuation, symbols and spaces only (e.g. "— — —").
_NON_TEXT = re.compile(r"^[\p{P}\p{S}\s\d]+$")

#: Query parameters that only track a campaign or click, never change the page.
_TRACKING_EXACT = frozenset(
    {
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
    }
)
_TRACKING_PREFIXES = ("utm_", "ga_")


def normalize_url(url: str) -> str:
    """Return the canonical dedupe key for an absolute URL.

    Lowercases scheme and host, strips the fragment and default port, removes
    tracking query parameters (``utm_*``, ``gclid``, ``fbclid``, ``ref``, ...),
    sorts the remaining query pairs, and drops a trailing slash. Relative or
    scheme-less strings come back unchanged, so callers can key on the result
    without second-guessing.

    Args:
        url (str): URL as delivered by a search provider or redirect unwrap.

    Returns:
        str: Canonical form suitable as a set key across providers.
    """
    cleaned = url.strip()
    try:
        parsed = urlsplit(cleaned)
    except ValueError:
        return cleaned
    if not parsed.scheme or not parsed.netloc:
        return cleaned
    host = (parsed.hostname or "").removeprefix("www.")
    try:
        port = parsed.port
    except ValueError:
        return cleaned
    if ":" in host:
        host = f"[{host}]"
    default = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    if port is not None and not default:
        host = f"{host}:{port}"
    pairs = [
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if name.lower() not in _TRACKING_EXACT and not name.lower().startswith(_TRACKING_PREFIXES)
    ]
    pairs.sort()
    path = parsed.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), host, path, urlencode(pairs), ""))


def normalize_text(text: str) -> str:
    """Canonicalize extracted text. Shared post-step for every extractor.

    NFKC-normalizes, unescapes HTML entities, drops invisible/control chars,
    collapses whitespace per line, removes ornament-only lines (menus, rules,
    cookie banners) case-insensitively, and removes repeated lines, keeping
    the first occurrence.

    Args:
        text (str): Raw extracted text.

    Returns:
        str: Single-line normalized text.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = html_lib.unescape(text)
    text = _INVISIBLE.sub("", text)
    seen: set[str] = set()
    kept: list[str] = []
    for line in text.splitlines():
        clean = _WHITESPACE.sub(" ", line).strip()
        if not clean or _NON_TEXT.match(clean):
            continue
        key = clean.casefold()
        if key not in seen:
            seen.add(key)
            kept.append(clean)
    return " ".join(kept)


__all__ = ["normalize_text", "normalize_url"]
