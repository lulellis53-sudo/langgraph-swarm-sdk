"""Tests for Jev routing autolearn helpers."""

from __future__ import annotations

import json
from pathlib import Path

from Core.benchmark.jev_autolearn import (
    MisrouteCause,
    classify,
    learning_gain_score,
    run_golden_pass,
)


def test_classify_ok() -> None:
    cause, rewind = classify("Coder", "Coder", 0.9)
    assert cause == MisrouteCause.OK
    assert rewind == "none"


def test_classify_wrong_agent_mr2() -> None:
    cause, rewind = classify("Coder", "Tester", 0.9)
    assert cause == MisrouteCause.WRONG_AGENT
    assert rewind == "MR2"


def test_learning_gain_formula() -> None:
    gain = learning_gain_score(
        delta_accuracy_pct=10.0,
        delta_p50_latency_pct=-5.0,
        delta_tokens_pct=0.0,
        delta_memory_pct=0.0,
    )
    assert gain == round(0.40 * 10.0 - 0.25 * (-5.0), 2)


def test_run_golden_pass_records_low_confidence_not_wrong_agent(tmp_path: Path) -> None:
    buffer = tmp_path / "routing.jsonl"
    correct, total, _written = run_golden_pass(buffer_path=buffer)
    assert total == 13
    assert correct == total
    if buffer.is_file():
        for line in buffer.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            assert row["expected_agent"] == row["selected_agent"]
            assert row["cause"] in ("low_confidence",)
