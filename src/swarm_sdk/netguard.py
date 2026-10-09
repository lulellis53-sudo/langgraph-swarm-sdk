"""Shared URL validation for outbound SDK HTTP calls (SSRF guard).

Every dynamic peer/endpoint URL passes :func:`validate_http_url` before it is
used in a server-side request: http/https schemes only, a real host, and no
control characters that could split headers or smuggle redirects.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

__all__ = ["validate_http_url"]

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def validate_http_url(url: str) -> str:
    """Validate an outbound URL and return it unchanged.

    Accepts absolute ``http``/``https`` URLs only. Loopback, link-local,
    private, and reserved literal IPs are rejected (cloud metadata ranges
    included); DNS names are left to the caller's egress policy.

    Args:
        url: Absolute peer/endpoint URL to validate.

    Returns:
        The URL unchanged, so it can be used inline.

    Raises:
        ValueError: When the URL is not an absolute http(s) URL with a usable
            host, or when it carries control characters.
    """
    if not url or any(char in url for char in "\r\n\t"):
        raise ValueError("url is empty or carries control characters")
    parts = urlsplit(url)
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError(f"url scheme must be http or https, got {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise ValueError("url has no host")
    if host in {"localhost", "0.0.0.0", "::1"} or host.endswith(".local"):
        raise ValueError(f"loopback host is not allowed: {host!r}")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return url  # DNS name: egress filtering happens at request time
    if address.is_private or address.is_loopback or address.is_reserved or address.is_link_local:
        raise ValueError(f"private or reserved IP is not allowed: {host!r}")
    return url
