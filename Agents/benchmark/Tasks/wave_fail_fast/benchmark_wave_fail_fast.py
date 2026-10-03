"""Measure fail-fast wave abort against the ``asyncio.gather`` behavior it replaced.

The baseline runs the exact pre-TaskGroup ``bounded_gather`` body inline
(``asyncio.gather`` over a semaphore): when one step fails, its siblings keep
running and burn provider tokens to completion. The current side uses the SDK's
TaskGroup-based ``bounded_gather``, which cancels in-flight siblings at once.
Tokens are a fixed per-call cost charged on completion only, so cancelled calls
stop burning. ``improvement_pct`` is measured, never hardcoded.
"""

from __future__ import annotations

import asyncio
import statistics
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, cast

from swarm_sdk.models.selection import bounded_gather

_RUNS = 5
_STEPS = 6
_MAX_CONCURRENCY = 3
_FAIL_MS = 5
_STEP_MS = 50
_TOKENS_PER_CALL = 100


async def _call(burned: list[int], *, fail: bool) -> int:
    await asyncio.sleep(_FAIL_MS / 1000 if fail else _STEP_MS / 1000)
    if fail:
        raise RuntimeError("provider down")
    burned.append(_TOKENS_PER_CALL)
    return _TOKENS_PER_CALL


async def _legacy_gather(
    coro_factories: Sequence[Callable[[], Awaitable[int]]],
    max_concurrency: int,
) -> list[int]:
    """The exact pre-TaskGroup body of ``bounded_gather`` (documented baseline)."""
    semaphore = asyncio.Semaphore(max_concurrency)

    async def run(factory: Callable[[], Awaitable[int]]) -> int:
        async with semaphore:
            return await factory()

    return list(await asyncio.gather(*(run(f) for f in coro_factories)))


async def _scenario(*, use_legacy: bool) -> tuple[float, float]:
    """One failing wave; returns ``(tokens_burned, siblings_still_running)``."""
    burned: list[int] = []
    factories = [(lambda index=index: _call(burned, fail=index == 0)) for index in range(_STEPS)]
    try:
        if use_legacy:
            await _legacy_gather(factories, _MAX_CONCURRENCY)
        else:
            await bounded_gather(factories, max_concurrency=_MAX_CONCURRENCY)
    except RuntimeError:
        pass
    pending = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    await asyncio.sleep(_STEP_MS / 1000)
    return float(sum(burned)), float(len(pending))


def _metric(
    name: str,
    baseline: float,
    current: float,
    *,
    higher_is_better: bool,
    detail: dict[str, Any],
) -> dict[str, Any]:
    """One report row; ``improvement_pct`` needs a non-zero baseline."""
    if baseline:
        improvement = (current - baseline) / baseline * 100.0
        if not higher_is_better:
            improvement = -improvement
    else:
        improvement = float("nan")
    return {
        "name": name,
        "baseline": round(baseline, 4),
        "current": round(current, 4),
        "improvement_pct": round(improvement, 2) if improvement == improvement else None,
        "delta_pp": round(current - baseline, 4),
        "higher_is_better": higher_is_better,
        "detail": detail,
    }


def run() -> dict[str, Any]:
    """Run the fail-fast wave scenario and return the report dict."""
    legacy = [asyncio.run(_scenario(use_legacy=True)) for _ in range(_RUNS)]
    current = [asyncio.run(_scenario(use_legacy=False)) for _ in range(_RUNS)]
    detail = {
        "runs": _RUNS,
        "steps": _STEPS,
        "max_concurrency": _MAX_CONCURRENCY,
        "fail_after_ms": _FAIL_MS,
        "step_ms": _STEP_MS,
        "tokens_per_call": _TOKENS_PER_CALL,
    }
    metrics = [
        _metric(
            "wave_tokens_burned",
            statistics.median(burned for burned, _ in legacy),
            statistics.median(burned for burned, _ in current),
            higher_is_better=False,
            detail=detail,
        ),
        _metric(
            "siblings_still_running",
            statistics.median(siblings for _, siblings in legacy),
            statistics.median(siblings for _, siblings in current),
            higher_is_better=False,
            detail=detail,
        ),
    ]
    measured = [
        cast(float, item["improvement_pct"])
        for item in metrics
        if item["improvement_pct"] is not None
    ]
    return {
        "runs": _RUNS,
        "metrics": metrics,
        "mean_improvement_pct": round(statistics.mean(measured), 2) if measured else None,
        "selection": "measured baseline (asyncio.gather body, inline) vs TaskGroup bounded_gather",
    }
