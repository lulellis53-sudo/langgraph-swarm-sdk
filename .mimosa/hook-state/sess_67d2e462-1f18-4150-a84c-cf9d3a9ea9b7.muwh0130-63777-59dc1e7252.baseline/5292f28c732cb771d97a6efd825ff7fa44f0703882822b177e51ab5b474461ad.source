"""Tune ``AgentPromptIndex`` retrieval knobs against labeled routing prompts."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from swarm_sdk.agents.prompt_index import AgentPromptIndex, IndexParams
from swarm_sdk.tuning.study import ChoiceParam, IntParam, ParamValue, tune

__all__ = [
    "RoutingCase",
    "RoutingScore",
    "RoutingTuning",
    "load_cases",
    "main",
    "score_routing",
    "split_cases",
    "tune_routing",
    "tuning_objective",
]

logger = logging.getLogger(__name__)

_MIN_CASES = 4
_K_PENALTY = 0.01
_SPACE = (
    IntParam("max_chunk_size", 300, 3000),
    ChoiceParam("sublinear_tf", (True, False)),
    IntParam("name_boost", 0, 3),
    IntParam("k", 1, 8),
)


@dataclass(frozen=True, slots=True)
class RoutingCase:
    """A prompt and the agent that should handle it."""

    prompt: str
    agent: str


@dataclass(frozen=True, slots=True)
class RoutingScore:
    """Top-1 accuracy and recall@k over a set of cases."""

    top1: float
    recall_at_k: float
    n: int

    @property
    def objective(self) -> float:
        """Single score used by the tuner: accuracy first, recall as a tie-breaker."""
        return self.top1 + 0.1 * self.recall_at_k


@dataclass(frozen=True, slots=True)
class RoutingTuning:
    """Baseline and tuned scores on the train and hold-out splits."""

    best: IndexParams
    baseline_train: RoutingScore
    best_train: RoutingScore
    baseline_holdout: RoutingScore
    best_holdout: RoutingScore


def load_cases(path: Path) -> list[RoutingCase]:
    """Read routing cases from a JSON list of ``{"prompt", "agent"}`` objects.

    Raises:
        ValueError: If the file holds no cases or an entry lacks ``prompt`` or ``agent``.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not raw:
        raise ValueError(f"no cases in {path}")
    cases: list[RoutingCase] = []
    for entry in raw:
        if not isinstance(entry, dict) or not {"prompt", "agent"} <= entry.keys():
            raise ValueError(f"each case needs a prompt and an agent: {entry!r}")
        cases.append(RoutingCase(str(entry["prompt"]), str(entry["agent"])))
    return cases


def score_routing(index: AgentPromptIndex, cases: Sequence[RoutingCase], k: int) -> RoutingScore:
    """Score ``index`` on ``cases``: share routed correctly first, and within the top ``k``."""
    if not cases:
        raise ValueError("no cases to score")
    top1 = 0
    recall = 0
    for case in cases:
        hits = index.search(case.prompt, k)
        top1 += bool(hits) and hits[0].agent == case.agent
        recall += case.agent in {hit.agent for hit in hits}
    return RoutingScore(top1 / len(cases), recall / len(cases), len(cases))


def split_cases(
    cases: Sequence[RoutingCase],
) -> tuple[list[RoutingCase], list[RoutingCase]]:
    """Split alternately into (train, hold-out) so both see every kind of prompt."""
    return list(cases[0::2]), list(cases[1::2])


def tuning_objective(score: RoutingScore, k: int) -> float:
    """Return the value the tuner maximizes: ``score.objective`` minus a small cost per ``k``."""
    return score.objective - _K_PENALTY * k


def _params(values: Mapping[str, ParamValue]) -> IndexParams:
    """Build ``IndexParams`` from a tuner assignment."""
    return IndexParams(
        max_chunk_size=int(values["max_chunk_size"]),
        sublinear_tf=bool(values["sublinear_tf"]),
        name_boost=int(values["name_boost"]),
        k=int(values["k"]),
    )


def tune_routing(
    agents_dir: Path,
    cases: Sequence[RoutingCase],
    *,
    n_trials: int,
    seed: int = 0,
) -> RoutingTuning:
    """Search ``IndexParams`` on the train split and report the hold-out split too.

    Raises:
        ValueError: If there are fewer than 4 cases or a label names an unknown agent.
    """
    if len(cases) < _MIN_CASES:
        raise ValueError(f"need at least {_MIN_CASES} cases, got {len(cases)}")
    baseline = IndexParams()
    unknown = {case.agent for case in cases} - AgentPromptIndex.build(agents_dir).agents
    if unknown:
        raise ValueError(f"unknown agent label(s): {sorted(unknown)}")
    train, holdout = split_cases(cases)

    def evaluate(values: dict[str, ParamValue]) -> float:
        """Score one parameter assignment on the train split."""
        params = _params(values)
        score = score_routing(AgentPromptIndex.build(agents_dir, params=params), train, params.k)
        return tuning_objective(score, params.k)

    result = tune(_SPACE, evaluate, n_trials=n_trials, seed=seed, warm_start=[asdict(baseline)])
    best = _params(result.best_params)
    base_index = AgentPromptIndex.build(agents_dir, params=baseline)
    best_index = AgentPromptIndex.build(agents_dir, params=best)
    return RoutingTuning(
        best=best,
        baseline_train=score_routing(base_index, train, baseline.k),
        best_train=score_routing(best_index, train, best.k),
        baseline_holdout=score_routing(base_index, holdout, baseline.k),
        best_holdout=score_routing(best_index, holdout, best.k),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tuner and print a JSON report (offline; no keys, no network)."""
    parser = argparse.ArgumentParser(description="Tune prompt-routing retrieval knobs.")
    parser.add_argument("--agents-dir", type=Path, default=Path("Agents"))
    parser.add_argument(
        "--cases", type=Path, default=Path("Agents/benchmark/Tasks/routing/cases.json")
    )
    parser.add_argument("--trials", type=int, default=40)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    result = tune_routing(
        args.agents_dir, load_cases(args.cases), n_trials=args.trials, seed=args.seed
    )
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
