"""Contract models for the Math Expert agent: problems, dispatch decisions and results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

type MathMode = Literal["dispatch", "solve", "verify"]
type MathTaskType = Literal[
    "matrix", "vector", "stats", "calculus", "optimization", "arithmetic", "proof"
]
type MathBackend = Literal["opencl", "molten", "numpy", "llm", "sympy", "pyarrow"]
type ThinkLevel = Literal["low", "medium", "high", "xhigh"]


class MathProblem(BaseModel):
    """A mathematical task submitted to the Math Expert agent."""

    problem_statement: str = Field(min_length=1)
    task_type: MathTaskType
    mode: MathMode = "solve"
    shape: tuple[int, ...] | None = None
    precision_tolerance: float = Field(default=1e-6, gt=0.0)
    force_gpu: bool = False
    think_level: ThinkLevel | None = None


class VerificationResult(BaseModel):
    """Outcome of checking a claim with a reproducible script."""

    verified: bool
    method: str
    script_snippet: str = ""
    error_bound: float | None = 0.0
    detail: str = ""


class MathDispatchDecision(BaseModel):
    """Where a task should run: GPU, CPU BLAS or an LLM route."""

    backend: MathBackend
    gpu_enabled: bool
    selected_route: dict[str, str]
    think_level: ThinkLevel = "low"
    notes: str = ""


class MathResult(BaseModel):
    """End-to-end result of a dispatch, solve or verify run."""

    task_id: str
    status: Literal["done", "blocked"]
    mode: MathMode
    selected_route: dict[str, str]
    gpu_enabled: bool
    backend: MathBackend
    solution: dict[str, Any] = Field(default_factory=dict)
    verification: VerificationResult | None = None
    notes: str = ""


__all__ = [
    "MathBackend",
    "MathDispatchDecision",
    "MathMode",
    "MathProblem",
    "MathResult",
    "MathTaskType",
    "ThinkLevel",
    "VerificationResult",
]
