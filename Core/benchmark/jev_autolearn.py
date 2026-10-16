"""Record routing outcomes and summarize autolearn signals for Jev Choice tuning."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from Core.benchmark.tasks.jev_agent_routing.cases import (
    AGENT_ROUTING_CASES,
    REVIEW_CONFIDENCE_BELOW,
    SWARM_AGENT_CANDIDATES,
)
from swarm_sdk.core.jev_router import JevRouter

_WORKSPACE = Path(__file__).resolve().parents[2]
_DEFAULT_BUFFER = _WORKSPACE / "Agents" / "Judge" / "Benchmark" / "routing_experience.jsonl"


class MisrouteCause(StrEnum):
    """Heuristic bucket for autolearn triage."""

    OK = "ok"
    LOW_CONFIDENCE = "low_confidence"
    WRONG_AGENT = "wrong_agent"
    LOW_CONFIDENCE_AND_WRONG = "low_confidence_and_wrong"


@dataclass(frozen=True, slots=True)
class RoutingExperienceRecord:
    """One measured routing attempt for the autolearn buffer."""

    timestamp: float
    goal: str
    expected_agent: str
    selected_agent: str
    confidence: float
    cause: str
    suggested_rewind: str


def classify(
    expected: str, selected: str, confidence: float
) -> tuple[MisrouteCause, str]:
    """Return misroute cause and multirouter rewind tag (MR2 when agent wrong)."""
    wrong = selected != expected
    low = confidence < REVIEW_CONFIDENCE_BELOW
    if not wrong and not low:
        return MisrouteCause.OK, "none"
    if wrong and low:
        return MisrouteCause.LOW_CONFIDENCE_AND_WRONG, "MR2"
    if wrong:
        return MisrouteCause.WRONG_AGENT, "MR2"
    return MisrouteCause.LOW_CONFIDENCE, "MR2"


def append_record(path: Path, record: RoutingExperienceRecord) -> None:
    """Append one JSON line to the experience buffer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def run_golden_pass(
    router: JevRouter | None = None,
    *,
    buffer_path: Path = _DEFAULT_BUFFER,
    record_all: bool = False,
) -> tuple[int, int, list[RoutingExperienceRecord]]:
    """Evaluate golden cases; record misroutes and low-confidence correct routes.

    Returns:
        Tuple of (correct_count, total_count, records_written_this_run).
    """
    jev = router or JevRouter(endpoint=None, api_key="")
    roster = list(SWARM_AGENT_CANDIDATES)
    correct = 0
    written: list[RoutingExperienceRecord] = []

    for goal, expected in AGENT_ROUTING_CASES:
        decision = jev.evaluate_choice(goal, roster)
        cause, rewind = classify(expected, decision.selected_choice, decision.confidence)
        if decision.selected_choice == expected:
            correct += 1
        if cause != MisrouteCause.OK or record_all:
            rec = RoutingExperienceRecord(
                timestamp=time.time(),
                goal=goal,
                expected_agent=expected,
                selected_agent=decision.selected_choice,
                confidence=round(decision.confidence, 4),
                cause=cause.value,
                suggested_rewind=rewind if cause != MisrouteCause.OK else "none",
            )
            if cause != MisrouteCause.OK:
                append_record(buffer_path, rec)
            written.append(rec)

    return correct, len(AGENT_ROUTING_CASES), written


def learning_gain_score(
    *,
    delta_accuracy_pct: float,
    delta_p50_latency_pct: float,
    delta_tokens_pct: float,
    delta_memory_pct: float,
) -> float:
    """Same weighting as Judge ``BenchmarkDelta`` learning gain (percent deltas)."""
    return round(
        (0.40 * delta_accuracy_pct)
        - (0.25 * delta_p50_latency_pct)
        - (0.20 * delta_tokens_pct)
        - (0.15 * delta_memory_pct),
        2,
    )


def load_buffer(path: Path = _DEFAULT_BUFFER) -> list[dict[str, object]]:
    """Read all records from the routing experience buffer."""
    if not path.is_file():
        return []
    out: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def report_buffer(path: Path = _DEFAULT_BUFFER) -> str:
    """Summarize buffer counts by cause for CLI."""
    rows = load_buffer(path)
    if not rows:
        return f"No records at {path}"
    by_cause: dict[str, int] = {}
    for row in rows:
        key = str(row.get("cause", "unknown"))
        by_cause[key] = by_cause.get(key, 0) + 1
    parts = ", ".join(f"{k}={v}" for k, v in sorted(by_cause.items()))
    return f"{len(rows)} record(s) at {path}: {parts}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jev routing autolearn buffer utilities")
    parser.add_argument("--report", action="store_true", help="Summarize routing_experience.jsonl")
    parser.add_argument("--run", action="store_true", help="Run golden pass and record misroutes")
    parser.add_argument(
        "--buffer",
        type=Path,
        default=_DEFAULT_BUFFER,
        help="Path to routing experience JSONL",
    )
    args = parser.parse_args(argv)

    if args.report:
        print(report_buffer(args.buffer))
        return 0

    if args.run:
        correct, total, written = run_golden_pass(buffer_path=args.buffer)
        misroutes = sum(1 for r in written if r.cause != MisrouteCause.OK.value)
        print(f"accuracy={correct}/{total} misroutes_recorded={misroutes}")
        print(report_buffer(args.buffer))
        return 0 if correct == total else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
