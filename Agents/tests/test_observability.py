"""Metrics and tracing helpers are safe to call with or without their extras."""

from __future__ import annotations

from swarm_sdk.observability import metrics


def test_metrics_calls_never_raise() -> None:
    metrics.record_request("swarm", False)
    metrics.record_tokens("coder", "openai:gpt-4o-mini", 12)
    metrics.record_cache_hit("exact")
    metrics.observe_step("route", 0.01)
    metrics.set_active_threads(3)


def test_metrics_enabled_matches_import() -> None:
    try:
        import prometheus_client  # noqa: F401
    except ImportError:
        assert metrics.ENABLED is False
    else:
        assert metrics.ENABLED is True
