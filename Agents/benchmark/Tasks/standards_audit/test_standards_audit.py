"""CI-sized check for the standards-audit benchmark: coverage is measured, and complete."""

from __future__ import annotations

from benchmark.Tasks.standards_audit.benchmark_standards_audit import audit_file, run


def test_audit_file_counts_each_rule() -> None:
    good = (
        '"""Doc."""\n\nfrom __future__ import annotations\n\n'
        'def f(x: int) -> int:\n    """Doc."""\n    return x\n'
    )
    bad = "def f(x):\n    return x\n"
    g, b = audit_file(good), audit_file(bad)
    assert (g.module_doc_ok, g.future_ok, g.pub_doc_ok, g.pub_ann_ok) == (1, 1, 1, 1)
    assert (b.module_doc_ok, b.future_ok, b.pub_doc_ok, b.pub_ann_ok) == (0, 0, 0, 0)


def test_working_tree_is_fully_covered_and_better_than_baseline() -> None:
    report = run()
    by_name = {m["name"]: m for m in report["metrics"]}
    for name in ("module_docstring_pct", "public_docstring_pct", "public_annotation_pct"):
        assert by_name[name]["current"] == 100.0, name
        assert by_name[name]["current"] >= by_name[name]["baseline"], name
    assert by_name["future_import_pct"]["current"] > by_name["future_import_pct"]["baseline"]
    assert by_name["audit_files_per_s"]["current"] > 0.0
    assert report["mean_improvement_pct"] is not None
