"""Benchmark 20 code-agent tasks and report per-task metrics.

Uses the reference implementations as a deterministic scripted Coder agent so
the suite requires no API keys and runs in CI.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
from cases import BENCH_CASES, CodeBenchCase
from scorer import CodeAgentScorer, TaskMetrics

PASS_MEAN_TASK_SCORE = 0.85
PASS_PASS_RATE = 0.95
MAX_TOTAL_TOKENS = 20000


def _reference_agent(case: CodeBenchCase) -> tuple[str, str, str]:
    """Deterministic Coder agent that returns the reference solution."""
    prompt = (
        f"You are a senior software engineer. {case.prompt}\n"
        "Write only the code, no explanation."
    )
    completion = case.reference
    return prompt, completion, case.reference


def _summarize(results: list[TaskMetrics]) -> dict[str, Any]:
    scores = [m.task_score for m in results]
    tokens = [m.token_usage for m in results]
    latencies = [m.latency_ms for m in results]
    passed = sum(m.tests_passed for m in results)
    total = sum(m.tests_total for m in results)

    return {
        "case_count": len(results),
        "mean_task_score": round(sum(scores) / len(scores), 3) if results else 0.0,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "total_tokens": sum(tokens),
        "mean_token_usage": round(sum(tokens) / len(tokens), 1) if results else 0.0,
        "max_token_usage": max(tokens) if tokens else 0,
        "total_latency_ms": round(sum(latencies), 3),
        "mean_latency_ms": round(sum(latencies) / len(latencies), 3) if results else 0.0,
        "tests_passed": passed,
        "tests_total": total,
        "files_changed": sum(m.files_changed for m in results),
        "lines_changed": sum(m.lines_changed for m in results),
    }


def _print_report(results: list[TaskMetrics], summary: dict[str, Any]) -> None:
    header = (
        f"{'case_id':<18} {'title':<24} {'diff':<6} {'think':<6} "
        f"{'score':>6} {'tokens':>8} {'ms':>10} {'pass':>6}"
    )
    print(header)
    print("-" * len(header))
    for m in results:
        print(
            f"{m.case_id:<18} {m.title:<24} {m.difficulty:<6} "
            f"{m.think_level:<6} {m.task_score:>6.1f} {m.token_usage:>8} "
            f"{m.latency_ms:>10.3f} {m.pass_rate:>6.2f}"
        )
    print("-" * len(header))
    print(json.dumps(summary, indent=2))


def run() -> None:
    """Entry point for ``python -m benchmark.run --task codeagent_bencheval``."""
    with tempfile.TemporaryDirectory(prefix="codeagent_bencheval_") as tmp:
        tmp_path = Path(tmp)
        scorer = CodeAgentScorer(tmp_root=tmp_path)
        results = scorer.score_all(_reference_agent)
        summary = _summarize(results)
        _print_report(results, summary)
        _write_results(tmp_path, results, summary)

        if summary["mean_task_score"] < PASS_MEAN_TASK_SCORE:
            raise SystemExit("mean task score below threshold")
        if summary["pass_rate"] < PASS_PASS_RATE:
            raise SystemExit("pass rate below threshold")
        if summary["total_tokens"] > MAX_TOTAL_TOKENS:
            raise SystemExit("total token usage above threshold")


@pytest.fixture
def scorer(tmp_path: Path) -> CodeAgentScorer:
    return CodeAgentScorer(tmp_root=tmp_path)


def test_codeagent_bencheval_all_cases(scorer: CodeAgentScorer, tmp_path: Path) -> None:
    results = scorer.score_all(_reference_agent)
    summary = _summarize(results)
    _print_report(results, summary)

    _write_results(tmp_path, results, summary)

    assert summary["mean_task_score"] >= PASS_MEAN_TASK_SCORE
    assert summary["pass_rate"] >= PASS_PASS_RATE
    assert summary["total_tokens"] <= MAX_TOTAL_TOKENS


def _write_results(
    tmp_path: Path, results: list[TaskMetrics], summary: dict[str, Any]
) -> None:
    out = {
        "task": "codeagent_bencheval",
        "summary": summary,
        "cases": [m.to_dict() for m in results],
    }
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "latest.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


@pytest.mark.parametrize("case", BENCH_CASES, ids=lambda c: c.id)
def test_codeagent_single_case(scorer: CodeAgentScorer, case: CodeBenchCase) -> None:
    prompt, completion, code = _reference_agent(case)
    metrics = scorer.score_case(case, code, prompt, completion)
    assert metrics.task_score == 1.0, metrics.error
