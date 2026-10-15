"""Measure cold ``import swarm_sdk`` against the eager-import stack it replaced.

Before the SDK went lazy, ``import swarm_sdk`` eagerly pulled ``langchain.agents``,
``langchain_core``, ``langgraph``, ``langgraph_swarm``, and ``tokenizers``. The
baseline reconstructs that legacy cost in a fresh subprocess (SDK import plus the
eager stack); the current side imports the SDK alone. Both sides are medians over
fresh subprocesses on an ABBA cadence, so warm ``sys.modules`` and linear machine
drift cannot land on only one side.
``improvement_pct`` is measured, never hardcoded.
"""

from __future__ import annotations

import statistics
import subprocess
import sys
from typing import Any, cast

from benchmark.protocol import abba, paired_deltas

_ABBA_ROUNDS = 5

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


def _time_snippet(code: str) -> float:
    """Return one fresh-process snippet time in milliseconds.

    Raises:
        subprocess.TimeoutExpired: When the child exceeds 300 seconds.
        subprocess.CalledProcessError: When the child exits non-zero.
        ValueError: When the child does not print a float.
    """
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    return float(proc.stdout.strip())


def _paired_samples(codes: dict[str, str], rounds: int = _ABBA_ROUNDS) -> dict[str, list[float]]:
    """Time two snippets in fresh subprocesses on an ABBA cadence.

    Even rounds run first, second, second, first. Odd rounds swap. Each round
    contributes two samples per snippet. The rotation cancels linear drift that
    a plain A-then-B alternation leaves on one side.

    Args:
        codes: Exactly two snippets, in variant order.
        rounds: Number of four-step cadences.

    Returns:
        Millisecond samples for each snippet, length ``2 * rounds``.

    Raises:
        ValueError: When ``codes`` does not contain two snippets.
    """
    names = list(codes)
    if len(names) != 2:
        raise ValueError("ABBA pairing needs exactly two snippets")
    first, second = names
    first_samples, second_samples = abba(
        lambda: _time_snippet(codes[first]),
        lambda: _time_snippet(codes[second]),
        rounds=rounds,
    )
    return {first: first_samples, second: second_samples}


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
    samples = _paired_samples({"current": _CURRENT, "legacy": _LEGACY})
    current = statistics.median(samples["current"])
    legacy_total = statistics.median(samples["legacy"])
    paired = paired_deltas(samples["current"], samples["legacy"])
    metrics = [
        _metric(
            "cold_import_ms",
            legacy_total,
            current,
            higher_is_better=False,
            detail={
                "runs": len(samples["current"]),
                "design": "ABBA",
                "paired_delta_p50_ms": round(statistics.median(paired), 4),
                "reconstructed_eager_stack_ms": round(legacy_total - current, 1),
                "current_min_ms": round(min(samples["current"]), 1),
                "current_max_ms": round(max(samples["current"]), 1),
                "legacy_min_ms": round(min(samples["legacy"]), 1),
                "legacy_max_ms": round(max(samples["legacy"]), 1),
            },
        )
    ]
    measured = [
        cast(float, item["improvement_pct"])
        for item in metrics
        if item["improvement_pct"] is not None
    ]
    return {
        "runs": len(samples["current"]),
        "design": "ABBA",
        "metrics": metrics,
        "mean_improvement_pct": round(statistics.mean(measured), 2) if measured else None,
        "selection": "measured baseline (eager import stack, fresh subprocesses) vs lazy SDK",
    }
