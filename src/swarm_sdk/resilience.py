"""Circuit breaker for provider/model calls.

States: closed -> (failures >= threshold) -> open -> (cooldown elapsed) -> half_open
A success in half_open closes the breaker; a failure reopens it.
"""

from __future__ import annotations

import time
from enum import Enum

from pydantic import BaseModel, Field


class CircuitOpenError(RuntimeError):
    """Raised when a call is attempted on an open circuit."""


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class BreakerConfig(BaseModel):
    failure_threshold: int = Field(default=3, ge=1)
    reset_timeout_s: float = Field(default=30.0, gt=0)
    half_open_max_probes: int = Field(default=1, ge=1)


class CircuitBreaker:
    """Per-provider circuit breaker. Not thread-safe; use one per event loop/task family."""

    def __init__(self, name: str, config: BreakerConfig | None = None) -> None:
        self.name = name
        self.config = config or BreakerConfig()
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._half_open_calls = 0

    @property
    def state(self) -> BreakerState:
        if self._state is BreakerState.OPEN and (time.monotonic() - self._opened_at) >= self.config.reset_timeout_s:
            self._state = BreakerState.HALF_OPEN
            self._half_open_calls = 0
        return self._state

    def before_call(self) -> None:
        state = self.state
        if state is BreakerState.OPEN:
            raise CircuitOpenError(f"circuit '{self.name}' is open")
        if state is BreakerState.HALF_OPEN:
            if self._half_open_calls >= self.config.half_open_max_probes:
                raise CircuitOpenError(f"circuit '{self.name}' is half-open (probe in flight)")
            self._half_open_calls += 1

    def record_success(self) -> None:
        self._failures = 0
        self._state = BreakerState.CLOSED

    def record_failure(self) -> None:
        if self._state is BreakerState.HALF_OPEN:
            self._trip()
            return
        self._failures += 1
        if self._failures >= self.config.failure_threshold:
            self._trip()

    def _trip(self) -> None:
        self._state = BreakerState.OPEN
        self._opened_at = time.monotonic()
        self._failures = 0
        self._half_open_calls = 0
