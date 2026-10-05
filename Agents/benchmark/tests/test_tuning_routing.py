"""Routing benchmark: scoring, case validation, hold-out split and the tuner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm_sdk.agents.prompt_index import AgentPromptIndex
from swarm_sdk.tuning.routing import (
    RoutingCase,
    RoutingScore,
    load_cases,
    score_routing,
    split_cases,
    tune_routing,
)

_AGENTS = Path("Agents")
_CASES = Path("Agents/benchmark/Tasks/routing/cases.json")


@pytest.fixture
def tiny_agents(tmp_path: Path) -> Path:
    for name, words in {"Alpha": "alpha apple anchor", "Beta": "beta banana basalt"}.items():
        folder = tmp_path / name
        folder.mkdir()
        (folder / "AGENTS.md").write_text(
            f"# Agent: {name}\n\n## Persona\n{words} {words} {words}\n", encoding="utf-8"
        )
    return tmp_path


def _tiny_cases() -> list[RoutingCase]:
    return [
        RoutingCase("alpha apple", "Alpha"),
        RoutingCase("beta banana", "Beta"),
        RoutingCase("anchor alpha", "Alpha"),
        RoutingCase("basalt beta", "Beta"),
    ]


def test_shipped_cases_load_and_name_real_agents() -> None:
    cases = load_cases(_CASES)
    assert len(cases) >= 18
    assert {case.agent for case in cases} <= AgentPromptIndex.build(_AGENTS).agents


def test_score_routing_is_perfect_on_separable_agents(tiny_agents: Path) -> None:
    index = AgentPromptIndex.build(tiny_agents)
    score = score_routing(index, _tiny_cases(), k=2)
    assert score == RoutingScore(top1=1.0, recall_at_k=1.0, n=4)
    assert score.objective == pytest.approx(1.1)


def test_split_cases_alternates_and_keeps_every_case() -> None:
    cases = _tiny_cases()
    train, holdout = split_cases(cases)
    assert train == cases[0::2]
    assert holdout == cases[1::2]


def test_load_cases_rejects_bad_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="no cases"):
        load_cases(empty)
    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps([{"prompt": "x"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="prompt.*agent"):
        load_cases(missing)


def test_tune_routing_rejects_unknown_labels_and_too_few_cases(tiny_agents: Path) -> None:
    with pytest.raises(ValueError, match="unknown agent"):
        tune_routing(tiny_agents, [*_tiny_cases(), RoutingCase("x", "Ghost")], n_trials=2)
    with pytest.raises(ValueError, match="at least 4"):
        tune_routing(tiny_agents, _tiny_cases()[:3], n_trials=2)


def test_tune_routing_never_loses_to_the_baseline(tiny_agents: Path) -> None:
    result = tune_routing(tiny_agents, _tiny_cases(), n_trials=6, seed=0)
    assert result.best_train.objective >= result.baseline_train.objective
    assert result.best_holdout.n == 2


def test_tune_routing_on_the_real_agents_is_reproducible() -> None:
    cases = load_cases(_CASES)
    first = tune_routing(_AGENTS, cases, n_trials=12, seed=0)
    second = tune_routing(_AGENTS, cases, n_trials=12, seed=0)
    assert first == second
    assert first.best_train.objective >= first.baseline_train.objective
    assert first.best_holdout.n == len(cases) // 2
