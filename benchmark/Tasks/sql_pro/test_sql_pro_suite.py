"""Pytest wrapper for the SQL Pro benchmarkable suite."""

from __future__ import annotations

import pytest
from benchmark.metrics import RunMetrics, Timer
from benchmark.sql_pro.harness import SqlProSuite


@pytest.fixture
def sql_pro_suite() -> SqlProSuite:
    return SqlProSuite()


@pytest.mark.parametrize(
    "case_id",
    [
        "window_latest_completed_order",
        "join_vs_correlated_subquery",
        "covering_index_customer_orders",
        "exists_active_orders",
    ],
)
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
