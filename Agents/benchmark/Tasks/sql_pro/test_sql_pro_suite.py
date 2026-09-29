"""Pytest wrapper for the SQL Pro benchmarkable suite."""

from __future__ import annotations

import pytest
from benchmark.metrics import RunMetrics, Timer
from benchmark.sql_pro.harness import SqlProSuite


def _suite_case_ids() -> list[str]:
    return [str(case["id"]) for case in SqlProSuite().cases]


@pytest.fixture
def sql_pro_suite() -> SqlProSuite:
    return SqlProSuite()


@pytest.mark.parametrize("case_id", _suite_case_ids())
def test_sql_pro_case(sql_pro_suite: SqlProSuite, case_id: str) -> None:
    case = next(c for c in sql_pro_suite.cases if c["id"] == case_id)
    result = sql_pro_suite.run_case(case)
    assert result.error is None, result.error
    assert result.passed, (result.notes, result.explain_plan)


def test_sql_pro_suite_all_pass(sql_pro_suite: SqlProSuite) -> None:
    with Timer() as timer:
        results = sql_pro_suite.run_all()
    metrics = [
        RunMetrics(
            task=f"sql_pro:{r.case_id}",
            latency_ms=r.latency_ms,
            extra={"row_count": float(r.row_count), "passed": float(r.passed)},
        )
        for r in results
    ]
    assert all(m.extra.get("passed") == 1.0 for m in metrics)
    assert timer.elapsed_ms >= 0


def run() -> None:
    """Entrypoint for ``python -m benchmark.run --task sql_pro``."""
    from benchmark.sql_pro.run import main

    raise SystemExit(main([]))
