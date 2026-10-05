"""Code-agent benchmark scoring harness.

The harness writes generated code to a temporary module, executes the case's
acceptance test, and records latency, token usage, and task score.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cases import BENCH_CASES, CodeBenchCase


def _token_counter() -> Callable[[str], int]:
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return lambda text: len(enc.encode(text))
    except Exception:
        return lambda text: max(1, len(text.split()))


token_counter: Callable[[str], int] = _token_counter()


@dataclass
class TaskMetrics:
    """Per-case scoring result: correctness, tokens and latency."""

    case_id: str
    title: str
    difficulty: str
    think_level: str
    effort: str
    task_score: float = 0.0
    token_usage: int = 0
    latency_ms: float = 0.0
    pass_rate: float = 0.0
    tests_passed: int = 0
    tests_total: int = 0
    files_changed: int = 0
    lines_changed: int = 0
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "case_id": self.case_id,
            "title": self.title,
            "difficulty": self.difficulty,
            "think_level": self.think_level,
            "effort": self.effort,
            "task_score": self.task_score,
            "token_usage": self.token_usage,
            "latency_ms": round(self.latency_ms, 3),
            "pass_rate": self.pass_rate,
            "tests_passed": self.tests_passed,
            "tests_total": self.tests_total,
            "files_changed": self.files_changed,
            "lines_changed": self.lines_changed,
        }
        if self.error:
            out["error"] = self.error
        out.update(self.extra)
        return out


class CodeAgentScorer:
    """Score one or more code-agent benchmark cases."""

    def __init__(self, tmp_root: Path | None = None) -> None:
        self.tmp_root = tmp_root or Path(tempfile.mkdtemp(prefix="codeagent_bencheval_"))
        self.tmp_root.mkdir(parents=True, exist_ok=True)

    def _write_solution(self, case: CodeBenchCase, code: str) -> Path:
        del case
        solution_path = self.tmp_root / "solution.py"
        solution_path.write_text(code, encoding="utf-8")
        return solution_path

    def _run_test(self, case: CodeBenchCase, solution_path: Path) -> tuple[bool, str]:
        test_module_name = f"test_{case.id}"
        test_path = self.tmp_root / f"{test_module_name}.py"
        test_path.write_text(case.test_code, encoding="utf-8")

        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            spec = importlib.util.spec_from_file_location(test_module_name, test_path)
            if spec is None or spec.loader is None:
                return False, "failed to load test module"
            module = importlib.util.module_from_spec(spec)

            sys.path.insert(0, str(self.tmp_root))
            original_solution = None
            if "solution" in sys.modules:
                original_solution = sys.modules.pop("solution")

            try:
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    spec.loader.exec_module(module)
            finally:
                sys.path.remove(str(self.tmp_root))
                if "solution" in sys.modules:
                    del sys.modules["solution"]
                if original_solution is not None:
                    sys.modules["solution"] = original_solution

            return True, ""
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def score_case(
        self,
        case: CodeBenchCase,
        generated_code: str,
        prompt_text: str,
        completion_text: str,
    ) -> TaskMetrics:
        metrics = TaskMetrics(
            case_id=case.id,
            title=case.title,
            difficulty=case.difficulty,
            think_level=case.think_level,
            effort=case.effort,
        )

        prompt_tokens = token_counter(prompt_text)
        completion_tokens = token_counter(completion_text)
        metrics.token_usage = prompt_tokens + completion_tokens
        metrics.files_changed = 1
        metrics.lines_changed = len(generated_code.splitlines())

        start = time.perf_counter()
        solution_path = self._write_solution(case, generated_code)
        passed, error = self._run_test(case, solution_path)
        elapsed = (time.perf_counter() - start) * 1000.0
        metrics.latency_ms = elapsed

        if passed:
            metrics.task_score = 1.0
            metrics.pass_rate = 1.0
            metrics.tests_passed = 1
            metrics.tests_total = 1
        else:
            metrics.error = error
            metrics.task_score = 0.0
            metrics.pass_rate = 0.0
            metrics.tests_passed = 0
            metrics.tests_total = 1

        return metrics

    def score_all(
        self,
        agent: Callable[[CodeBenchCase], tuple[str, str, str]],
    ) -> list[TaskMetrics]:
        results: list[TaskMetrics] = []
        for case in BENCH_CASES:
            prompt_text, completion_text, generated_code = agent(case)
            results.append(
                self.score_case(
                    case,
                    generated_code=generated_code,
                    prompt_text=prompt_text,
                    completion_text=completion_text,
                )
            )
        return results


__all__ = [
    "CodeAgentScorer",
    "TaskMetrics",
    "token_counter",
]
