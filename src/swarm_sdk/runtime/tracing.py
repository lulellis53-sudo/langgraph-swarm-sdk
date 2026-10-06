"""OpenTelemetry spans. A no-op unless ``opentelemetry-api`` is installed."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

try:
    from opentelemetry import trace
except ImportError:
    _TRACER = None
else:
    _TRACER = trace.get_tracer("swarm_sdk")


@contextmanager
def span(name: str, **attrs: str | int | float | bool) -> Iterator[None]:
    """Open a span named ``name`` with scalar attributes; no-op without OTel."""
    if _TRACER is None:
        yield
        return
    with _TRACER.start_as_current_span(name, attributes=attrs) as active:
        try:
            yield
        except BaseException as exc:
            active.record_exception(exc)
            raise


__all__ = ["span"]
