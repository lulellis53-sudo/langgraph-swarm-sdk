"""URL canonicalization shared by every layer."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit

#: Query params that never change the target page; dropped when deduplicating URLs.
_TRACKING_PARAMS = frozenset({"fbclid", "gclid", "msclkid", "ref", "ref_src"})


def normalize_url(url: str) -> str:
    """Return a canonical key for *url* so duplicates collapse.

    Lowercases scheme and host, drops ``www.``, fragments, trailing slashes,
    default ports and tracking params (``utm_*``, ``gclid``, ...), and sorts
    the remaining query params.

    Args:
        url (str): Absolute URL.

    Returns:
        str: Canonical form, used for comparison only.
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").removeprefix("www.")
    default_port = {"http": 80, "https": 443}.get(parts.scheme.lower())
    if parts.port is not None and parts.port != default_port:
        host = f"{host}:{parts.port}"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    )
    path = parts.path.rstrip("/")
    return f"{parts.scheme.lower()}://{host}{path}" + (f"?{urlencode(query)}" if query else "")


__all__ = ["normalize_url"]
