"""Seeded Optuna wrapper: optimum search, reproducibility and bad-input handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm_sdk.tuning import ChoiceParam, FloatParam, IntParam, tune

SPACE = [FloatParam("x", -5.0, 5.0), IntParam("n", 1, 8), ChoiceParam("mode", ("a", "b", "c"))]


def _score(p: dict) -> float:
    return -((p["x"] - 3.0) ** 2) - abs(p["n"] - 5) - (0 if p["mode"] == "b" else 1)


def test_finds_a_near_optimal_point() -> None:
    result = tune(SPACE, _score, n_trials=60, seed=0)
    assert len(result.history) == 60
    assert result.best_value == max(result.history)
    assert result.best_value > -2.0


def test_same_seed_is_reproducible() -> None:
    first = tune(SPACE, _score, n_trials=15, seed=7)
    second = tune(SPACE, _score, n_trials=15, seed=7)
    assert first == second


def test_warm_start_is_evaluated_first_and_never_beaten_backwards() -> None:
    optimum = {"x": 3.0, "n": 5, "mode": "b"}
    result = tune(SPACE, _score, n_trials=5, seed=1, warm_start=[optimum])
    assert result.history[0] == 0.0
    assert result.best_value == 0.0
    assert result.best_params == optimum


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_score_raises(bad: float) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        tune(SPACE, lambda _p: bad, n_trials=3)


@pytest.mark.parametrize(
    ("space", "n_trials", "message"),
    [
        (SPACE, 0, "n_trials"),
        ([], 3, "empty"),
        ([IntParam("n", 1, 2), IntParam("n", 3, 4)], 3, "duplicate"),
    ],
)
def test_invalid_arguments_raise(space: list, n_trials: int, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        tune(space, _score, n_trials=n_trials)


def test_leaves_no_files_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    tune(SPACE, _score, n_trials=3, seed=0)
    assert list(tmp_path.iterdir()) == []
