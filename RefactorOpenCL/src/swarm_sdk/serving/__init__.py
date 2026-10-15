"""Serving domain: HTTP (FastAPI), gRPC, and peer transport.

``app`` resolves lazily: building the default FastAPI app primes real
settings/secrets, so importing :mod:`swarm_sdk.serving` must not do it.
"""

from __future__ import annotations

from typing import Any

from swarm_sdk.serving.grpc import SwarmServicer, serve
from swarm_sdk.serving.http import RecallIn, RunIn, create_app
from swarm_sdk.serving.peer import async_post_json, post_json

__all__ = [
    "RecallIn",
    "RunIn",
    "SwarmServicer",
    "app",
    "async_post_json",
    "create_app",
    "post_json",
    "serve",
]


def __getattr__(name: str) -> Any:
    if name == "app":
        from swarm_sdk.serving import http

        return http.app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
