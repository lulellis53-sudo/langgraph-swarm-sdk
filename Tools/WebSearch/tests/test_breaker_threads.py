"""CircuitBreaker must hold its invariants under concurrent callers (free-threaded builds)."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest

from swarm_sdk.models.breaker import BreakerConfig, BreakerState, CircuitBreaker, CircuitOpenError

_THREADS = 32


@pytest.fixture(autouse=True)
def _aggressive_thread_switching() -> Iterator[None]:
    """Make races visible on GIL builds too: switch threads as often as possible."""
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(old)


def _run_in_threads(work, threads: int = _THREADS) -> None:  # noqa: ANN001 - test helper
    barrier = threading.Barrier(threads)

    def runner() -> None:
        barrier.wait()
        work()

    with ThreadPoolExecutor(max_workers=threads) as pool:
        for future in [pool.submit(runner) for _ in range(threads)]:
            future.result()


def test_concurrent_failures_are_all_counted() -> None:
    breaker = CircuitBreaker("p", BreakerConfig(failure_threshold=10**9))
    per_thread = 5000

    def work() -> None:
        for _ in range(per_thread):
            breaker.record_failure()

    _run_in_threads(work)
    assert breaker._failures == _THREADS * per_thread  # noqa: SLF001 - the invariant under test


def test_half_open_never_admits_more_probes_than_configured() -> None:
    breaker = CircuitBreaker(
        "p", BreakerConfig(failure_threshold=1, reset_timeout_s=0.001, half_open_max_probes=3)
    )
    breaker.record_failure()  # trips to OPEN
    time.sleep(0.01)  # cooldown elapsed: the next state read promotes to HALF_OPEN
    admitted: list[int] = []
    lock = threading.Lock()

    def work() -> None:
        try:
            breaker.before_call()
        except CircuitOpenError:
            return
        with lock:
            admitted.append(1)

    _run_in_threads(work)
    assert len(admitted) <= 3
    assert breaker.state is BreakerState.HALF_OPEN


def test_single_threaded_semantics_are_unchanged() -> None:
    breaker = CircuitBreaker("p", BreakerConfig(failure_threshold=2, reset_timeout_s=0.001))
    breaker.record_failure()
    assert breaker.state is BreakerState.CLOSED
    breaker.record_failure()
    assert breaker.state is BreakerState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.before_call()
    time.sleep(0.01)
    breaker.before_call()  # one probe allowed
    with pytest.raises(CircuitOpenError):
        breaker.before_call()
    breaker.record_success()
    assert breaker.state is BreakerState.CLOSED
