"""Peer HTTP clients: httpx2 (HTTP/2), aiohttp, and requests.

Every URL is screened by :func:`swarm_sdk.netguard.validate_http_url` before a
request leaves the process, so no caller can point a peer hop at loopback, a
private IP, or a cloud metadata endpoint.
"""

from __future__ import annotations

from typing import Any

import aiohttp
import httpx2
import requests

from swarm_sdk.netguard import validate_http_url

__all__ = ["async_post_json", "post_json", "validate_http_url"]


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    client: str = "httpx2",
    transport: httpx2.BaseTransport | None = None,
) -> dict[str, Any]:
    """POST JSON synchronously and return the decoded object body.

    Args:
        url: Absolute peer URL (validated: http/https, non-private host).
        payload: JSON-serializable request body.
        client: ``"httpx2"`` (default, HTTP/2) or ``"requests"``.
        transport: Optional httpx2 transport (tests / custom stacks).

    Returns:
        Response JSON object.

    Raises:
        TypeError: If the response body is not a JSON object.
        ValueError: If ``url`` fails the SSRF guard (non-http(s), no host,
            control characters, or a private/loopback/reserved IP).
        requests.HTTPError | httpx2.HTTPError: On non-success status.
    """
    validate_http_url(url)
    if client == "requests":
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        body = response.json()
    else:
        with httpx2.Client(http2=True, timeout=30.0, transport=transport) as http:
            response_http = http.post(url, json=payload)
            response_http.raise_for_status()
            body = response_http.json()
    if not isinstance(body, dict):
        raise TypeError("peer response must be a JSON object")
    return body


async def async_post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST JSON asynchronously with aiohttp.

    Args:
        url: Absolute peer URL.
        payload: JSON-serializable request body.

    Returns:
        Response JSON object.

    Raises:
        TypeError: If the response body is not a JSON object.
        ValueError: If ``url`` fails the SSRF guard (see :func:`post_json`).
        aiohttp.ClientResponseError: On non-success status.
    """
    validate_http_url(url)
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as response:
            response.raise_for_status()
            body = await response.json()
    if not isinstance(body, dict):
        raise TypeError("peer response must be a JSON object")
    return body
