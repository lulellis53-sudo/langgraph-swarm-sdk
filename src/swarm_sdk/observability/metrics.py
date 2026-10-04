"""Prometheus instruments. Every function is a no-op without ``prometheus-client``."""

from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge, Histogram
except ImportError:
    ENABLED = False
else:
    ENABLED = True
    _REQUESTS = Counter("swarm_requests_total", "Swarm runs", ["mode", "cached"])
    _TOKENS = Counter("swarm_token_usage_total", "Tokens charged", ["agent", "model"])
    _CACHE_HITS = Counter("swarm_cache_hits_total", "Cache hits", ["kind"])
    _STEP_SECONDS = Histogram("swarm_step_latency_seconds", "Step latency", ["step"])
    _THREADS = Gauge("swarm_active_threads", "Tracked conversation threads")
    _RETRIEVAL_SAVINGS = Counter(
        "swarm_retrieval_savings_total",
        "Items or tokens saved by retrieval optimizations",
        ["kind"],
    )


def record_request(mode: str, cached: bool) -> None:
    """Count one swarm run by mode and cache status."""
    if ENABLED:
        _REQUESTS.labels(mode=mode, cached=str(cached).lower()).inc()


def record_tokens(agent: str, model: str, tokens: int) -> None:
    """Accumulate token usage per agent and model."""
    if ENABLED and tokens > 0:
        _TOKENS.labels(agent=agent, model=model or "unknown").inc(tokens)


def record_cache_hit(kind: str) -> None:
    """Count one cache hit by kind (exact or semantic)."""
    if ENABLED:
        _CACHE_HITS.labels(kind=kind).inc()


def observe_step(step: str, seconds: float) -> None:
    """Observe one step's wall time in the latency histogram."""
    if ENABLED:
        _STEP_SECONDS.labels(step=step).observe(seconds)


def set_active_threads(count: int) -> None:
    """Update the active-thread gauge."""
    if ENABLED:
        _THREADS.set(count)


def record_retrieval_savings(kind: str, amount: int) -> None:
    """Count items or tokens saved by a retrieval optimization.

    Args:
        kind: What produced the savings (e.g. ``"dedupe"``).
        amount: Number of items or tokens saved; ignored if non-positive.
    """
    if ENABLED and amount > 0:
        _RETRIEVAL_SAVINGS.labels(kind=kind).inc(amount)


__all__ = [
    "ENABLED",
    "observe_step",
    "record_cache_hit",
    "record_request",
    "record_retrieval_savings",
    "record_tokens",
    "set_active_threads",
]
