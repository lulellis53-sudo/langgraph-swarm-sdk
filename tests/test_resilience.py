"""Circuit breaker state transitions."""

import time

from swarm_sdk.resilience import BreakerConfig, BreakerState, CircuitBreaker, CircuitOpenError


def test_breaker_starts_closed() -> None:
    breaker = CircuitBreaker("test")
    assert breaker.state == BreakerState.CLOSED


def test_breaker_trips_after_threshold() -> None:
    breaker = CircuitBreaker("test", BreakerConfig(failure_threshold=3))
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == BreakerState.CLOSED
    breaker.record_failure()
    assert breaker.state == BreakerState.OPEN


def test_open_breaker_rejects_calls() -> None:
    breaker = CircuitBreaker("test", BreakerConfig(failure_threshold=1))
    breaker.record_failure()
    try:
        breaker.before_call()
        raised = False
    except CircuitOpenError:
        raised = True
    assert raised


def test_success_resets_failure_count() -> None:
    breaker = CircuitBreaker("test", BreakerConfig(failure_threshold=2))
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.state == BreakerState.CLOSED, "count must restart after a success"


def test_half_open_after_cooldown() -> None:
    breaker = CircuitBreaker("test", BreakerConfig(failure_threshold=1, reset_timeout_s=0.01))
    breaker.record_failure()
    assert breaker.state == BreakerState.OPEN
    time.sleep(0.02)
    assert breaker.state == BreakerState.HALF_OPEN


def test_half_open_limits_probes() -> None:
    breaker = CircuitBreaker("test", BreakerConfig(failure_threshold=1, reset_timeout_s=0.01))
    breaker.record_failure()
    time.sleep(0.02)
    breaker.before_call()  # first probe allowed
    try:
        breaker.before_call()  # second probe rejected
        raised = False
    except CircuitOpenError:
        raised = True
    assert raised


def test_half_open_failure_reopens() -> None:
    breaker = CircuitBreaker("test", BreakerConfig(failure_threshold=1, reset_timeout_s=0.01))
    breaker.record_failure()
    time.sleep(0.02)
    assert breaker.state == BreakerState.HALF_OPEN
    breaker.record_failure()
    assert breaker.state == BreakerState.OPEN


def test_half_open_success_closes() -> None:
    breaker = CircuitBreaker("test", BreakerConfig(failure_threshold=1, reset_timeout_s=0.01))
    breaker.record_failure()
    time.sleep(0.02)
    breaker.record_success()
    assert breaker.state == BreakerState.CLOSED
