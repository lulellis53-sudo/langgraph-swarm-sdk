"""CI-sized check: the claims benchmark reports measured rows or explicit skips."""

from __future__ import annotations

from benchmark.Tasks.python315_claims.benchmark_python315_claims import format_table, run


def test_report_rows_are_measured_or_skipped_with_reason() -> None:
    report = run(quick=True)
    assert report["dossier"]["section"] == "Documents/Python3.15.md §11"
    assert {r["id"] for r in report["rows"]} == {"A", "B", "C", "D", "E", "F", "dot"}
    for row in report["rows"]:
        if row["status"] == "skipped":
            assert row["note"]
            continue
        assert row["baseline"] > 0 and row["target"] > 0
        assert row["speedup"] == row["baseline"] / row["target"]
    by_id = {r["id"]: r for r in report["rows"]}
    assert by_id["C"]["verified"] is True
    assert by_id["C"]["target"] <= by_id["C"]["baseline"]
    assert by_id["E"]["target"] < by_id["E"]["baseline"]
    assert by_id["dot"]["speedup"] > 1.0
    assert "skipped" in format_table(report)  # allocator row is always skipped here
