"""CI-sized checks for the efficiency-gains benchmark: every improvement is real."""

from __future__ import annotations

import sqlite3

from benchmark.Tasks.efficiency_gains.benchmark_efficiency_gains import run


def _by_name(report: dict, name: str) -> dict:
    return next(item for item in report["metrics"] if item["name"] == name)


def test_report_contains_all_metrics_with_numbers() -> None:
    report = run()
    names = {item["name"] for item in report["metrics"]}
    assert names == {
        "fanout_brief_tokens",
        "bge_m3_embed_tokens",
        "plan_recovery_rate_pct",
        "empty_reply_poison_rate_pct",
        "recall_prompt_tokens",
        "fts5_fallback_operational_pct",
    }
    for item in report["metrics"]:
        assert item["baseline"] >= 0.0
        assert item["current"] >= 0.0
    assert report["mean_improvement_pct"] is not None


def test_token_metrics_improve() -> None:
    report = run()
    fanout = _by_name(report, "fanout_brief_tokens")
    assert fanout["improvement_pct"] > 0.0
    prefix = _by_name(report, "bge_m3_embed_tokens")
    assert prefix["improvement_pct"] > 0.0
    recall = _by_name(report, "recall_prompt_tokens")
    assert recall["improvement_pct"] > 0.0


def test_plan_recovery_and_cache_integrity() -> None:
    report = run()
    recovery = _by_name(report, "plan_recovery_rate_pct")
    assert recovery["baseline"] == 0.0
    assert recovery["current"] == 100.0
    poison = _by_name(report, "empty_reply_poison_rate_pct")
    assert poison["baseline"] == 100.0
    assert poison["current"] == 0.0


def test_fts5_fallback_operational_and_accurate() -> None:
    report = run()
    item = _by_name(report, "fts5_fallback_operational_pct")
    detail = item["detail"]
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE probe USING fts5(x)")
        has_fts5 = True
    except sqlite3.Error:
        has_fts5 = False
    if not has_fts5:
        # On FTS5-less builds (this machine) the fallback is the whole win.
        assert item["baseline"] == 0.0
    assert item["current"] == 100.0
    assert detail["keyword_recall"] >= 0.99
