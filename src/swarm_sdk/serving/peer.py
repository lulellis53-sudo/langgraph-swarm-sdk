"""Peer HTTP clients: httpx2 (HTTP/2), aiohttp, and requests."""

from __future__ import annotations

from typing import Any

import aiohttp
import httpx2
import requests


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    client: str = "httpx2",
    transport: httpx2.BaseTransport | None = None,
) -> dict[str, Any]:
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
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as response:
            response.raise_for_status()
            body = await response.json()
    if not isinstance(body, dict):
        raise TypeError("peer response must be a JSON object")
    return body


__all__ = ["async_post_json", "post_json"]
