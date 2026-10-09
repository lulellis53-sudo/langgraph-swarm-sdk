"""Optional Sentry SDK bootstrap for WebSearch HTTP and CLI surfaces."""

from __future__ import annotations

import os
from typing import Any

__all__ = ["configure_sentry"]


def configure_sentry(**overrides: Any) -> bool:
    """Initialize sentry-sdk when ``SENTRY_DSN`` is set. Returns True if initialized."""
    dsn = overrides.pop("dsn", None) or os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.httpx import HttpxIntegration

    environment = (
        overrides.pop("environment", None)
        or os.environ.get("SENTRY_ENVIRONMENT", "development").strip()
    )
    traces_sample_rate = float(overrides.pop("traces_sample_rate", 0.1))
    send_default_pii = bool(overrides.pop("send_default_pii", False))

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=send_default_pii,
        integrations=[FastApiIntegration(), HttpxIntegration()],
        **overrides,
    )
    return True
