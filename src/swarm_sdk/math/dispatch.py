"""Hardware-aware dispatch for math tasks: GPU, CPU BLAS or an LLM route."""

from __future__ import annotations

import os

from swarm_sdk.math.types import MathBackend, MathDispatchDecision, MathProblem, ThinkLevel

_GPU_BACKENDS: dict[str, MathBackend] = {
    "opencl": "opencl",
    "molten": "molten",
    "metal": "molten",
    "vulkan": "molten",
}
_FRONTIER_ROUTE = {"name": "google:gemini-2.5-pro", "provider": "google"}
_FAST_ROUTE = {"name": "moonshot:kimi-k2.7-code", "provider": "moonshot"}
_BALANCED_ROUTE = {"name": "openai:gpt-6-luna", "provider": "codex"}
_NUMPY_ROUTE = {"name": "numpy_blas", "provider": "local_cpu"}


def _gpu_backend(problem: MathProblem) -> MathBackend | None:
    """GPU backend requested via ``SWARM_GPU_BACKEND`` / ``force_gpu``, else ``None``."""
    configured = _GPU_BACKENDS.get(os.environ.get("SWARM_GPU_BACKEND", "").strip().lower())
    if configured is not None:
        return configured
    return "opencl" if problem.force_gpu else None


def _rows(shape: tuple[int, ...] | None) -> int:
    """Return the leading dimension, or ``0`` when ``shape`` is missing."""
    return shape[0] if shape else 0


def _element_count(shape: tuple[int, ...] | None) -> int:
    """Return the product of ``shape``, or ``0`` when ``shape`` is missing."""
    if not shape:
        return 0
    total = 1
    for dim in shape:
        total *= dim
    return total


def _llm(route: dict[str, str], level: ThinkLevel, notes: str) -> MathDispatchDecision:
    """Build an LLM dispatch decision for ``route`` at ``level``."""
    return MathDispatchDecision(
        backend="llm",
        gpu_enabled=False,
        selected_route=route,
        think_level=level,
        notes=notes,
    )


def classify_math_task(
    problem: MathProblem, *, has_cache_key: bool = False
) -> MathDispatchDecision:
    """Choose where a math task should run.

    Dense matrix/vector work goes to the GPU only past the measured crossover
    (``SWARM_OPENCL_MIN_ROWS``, default 8192 rows) or when a resident buffer is
    cached; below it CPU BLAS wins because of PCIe transfer cost. Everything
    else routes to an LLM tier by reasoning demand.

    Args:
        problem: The task to route.
        has_cache_key: True when the operands already live in a resident GPU buffer.

    Returns:
        The dispatch decision; empty or zero-sized shapes always stay on the CPU.
    """
    if problem.task_type in {"matrix", "vector"}:
        from swarm_sdk.gpu.opencl_math import _gpu_threshold

        rows = _rows(problem.shape)
        elements = _element_count(problem.shape)
        backend = _gpu_backend(problem)
        # Cubic/complex operations win on the GPU sooner than simple matmul.
        cubic_ops = {"solve", "eig", "svd", "inv", "det"}
        is_cubic = problem.operation in cubic_ops
        effective_threshold = _gpu_threshold() // 4 if is_cubic else _gpu_threshold()
        # Float64 doubles PCIe traffic and compute; raise the bar.
        if problem.dtype == "float64":
            effective_threshold = int(effective_threshold * 1.5)
        # Element-count gate: only very large matrices benefit from GPU transfer
        # for simple matmul; cubic ops already lowered the row threshold.
        element_gate = effective_threshold * 256 if not is_cubic else effective_threshold * 128
        crossover = rows >= effective_threshold or elements >= element_gate or has_cache_key
        if backend is not None and rows > 0 and crossover:
            why = (
                "resident buffer"
                if has_cache_key and rows < effective_threshold
                else f"rows/elements >= crossover (op={problem.operation}, dtype={problem.dtype})"
            )
            return MathDispatchDecision(
                backend=backend,
                gpu_enabled=True,
                selected_route={"name": f"{backend}_math", "provider": "local_gpu"},
                notes=f"GPU: {why}",
            )
        return MathDispatchDecision(
            backend="numpy",
            gpu_enabled=False,
            selected_route=_NUMPY_ROUTE,
            notes="CPU BLAS: below crossover, empty shape or no GPU backend",
        )
    if problem.task_type in {"proof", "calculus", "optimization"}:
        stmt = problem.problem_statement.lower()
        symbolic_keywords = ("symbolic", "solve", "derivative", "integral", "diff")
        if problem.mode == "solve" and any(k in stmt for k in symbolic_keywords):
            return MathDispatchDecision(
                backend="sympy",
                gpu_enabled=False,
                selected_route={"name": "sympy_engine", "provider": "local_cpu"},
                think_level=problem.think_level or "medium",
                notes="SymPy exact symbolic calculation engine",
            )
        return _llm(
            _FRONTIER_ROUTE, problem.think_level or "high", "frontier reasoning + SymPy check"
        )
    if problem.task_type == "stats":
        stmt = problem.problem_statement.lower()
        stats_keywords = ("column", "arrow", "table", "quantile")
        if problem.mode == "solve" and any(k in stmt for k in stats_keywords):
            return MathDispatchDecision(
                backend="pyarrow",
                gpu_enabled=False,
                selected_route={"name": "pyarrow_compute", "provider": "local_cpu"},
                think_level=problem.think_level or "low",
                notes="PyArrow zero-copy columnar statistical engine",
            )
        return _llm(_BALANCED_ROUTE, problem.think_level or "medium", "balanced statistics route")
    return _llm(_FAST_ROUTE, problem.think_level or "low", "fast structured arithmetic route")


__all__ = ["classify_math_task"]
