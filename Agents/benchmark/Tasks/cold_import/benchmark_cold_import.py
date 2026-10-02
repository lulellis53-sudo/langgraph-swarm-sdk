"""Measure cold ``import swarm_sdk`` against the eager-import stack it replaced.

Before the SDK went lazy, ``import swarm_sdk`` eagerly pulled ``langchain.agents``,
``langchain_core``, ``langgraph``, ``langgraph_swarm``, and ``tokenizers``. The
baseline reconstructs that legacy cost in a fresh subprocess (SDK import plus the
eager stack); the current side imports the SDK alone. Both sides are medians over
fresh subprocesses, so warm ``sys.modules`` and bytecode caching cannot skew the
numbers. ``improvement_pct`` is measured, never hardcoded.
"""

from __future__ import annotations

import statistics
import subprocess
import sys
from typing import Any, cast

_RUNS = 3

_TIMER = "import time; t0 = time.perf_counter()"
_CURRENT = f"{_TIMER}; import swarm_sdk; print((time.perf_counter() - t0) * 1000)"
_EAGER_STACK = (
    "import langchain.agents;"
    "import langchain_core.language_models.chat_models;"
    "import langgraph.checkpoint.memory;"
    "import langgraph_swarm;"
    "import tokenizers;"
    "import tokenizers.pre_tokenizers"
)
_LEGACY = f"{_TIMER}; import swarm_sdk; {_EAGER_STACK}; print((time.perf_counter() - t0) * 1000)"


def _median_ms(code: str) -> float:
    """Median SDK import time in ms over fresh subprocess runs of ``code``."""
    samples = []
    for _ in range(_RUNS):
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            timeout=300,
        )
        samples.append(float(proc.stdout.strip()))
    return statistics.median(samples)


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
    """Run the cold-import scenario and return the report dict."""
    current = _median_ms(_CURRENT)
    legacy_total = _median_ms(_LEGACY)
    metrics = [
        _metric(
            "cold_import_ms",
            legacy_total,
            current,
            higher_is_better=False,
            detail={
                "runs": _RUNS,
                "reconstructed_eager_stack_ms": round(legacy_total - current, 1),
            },
        )
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
        "selection": "measured baseline (eager import stack, fresh subprocesses) vs lazy SDK",
    }
