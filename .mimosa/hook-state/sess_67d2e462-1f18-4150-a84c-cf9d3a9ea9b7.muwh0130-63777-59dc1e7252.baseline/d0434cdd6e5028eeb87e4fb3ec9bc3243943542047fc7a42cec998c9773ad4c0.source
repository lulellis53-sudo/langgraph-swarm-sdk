"""Seeded, in-memory hyperparameter search over a caller-supplied scoring function."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import optuna

__all__ = [
    "ChoiceParam",
    "FloatParam",
    "IntParam",
    "Param",
    "ParamValue",
    "TuneResult",
    "tune",
]

type ParamValue = int | float | str | bool


@dataclass(frozen=True, slots=True)
class IntParam:
    """Integer parameter in ``[low, high]`` (inclusive)."""

    name: str
    low: int
    high: int


@dataclass(frozen=True, slots=True)
class FloatParam:
    """Float parameter in ``[low, high]``, optionally sampled on a log scale."""

    name: str
    low: float
    high: float
    log: bool = False


@dataclass(frozen=True, slots=True)
class ChoiceParam:
    """Categorical parameter drawn from ``values``."""

    name: str
    values: tuple[ParamValue, ...]


type Param = IntParam | FloatParam | ChoiceParam


@dataclass(frozen=True, slots=True)
class TuneResult:
    """Outcome of a search: the best point, its score and every trial's score."""

    best_params: dict[str, ParamValue]
    best_value: float
    history: tuple[float, ...]


def _suggest(trial: optuna.Trial, param: Param) -> ParamValue:
    """Draw one parameter value for ``trial``."""
    match param:
        case IntParam(name=name, low=low, high=high):
            return trial.suggest_int(name, low, high)
        case FloatParam(name=name, low=low, high=high, log=log):
            return trial.suggest_float(name, low, high, log=log)
        case ChoiceParam(name=name, values=values):
            chosen = trial.suggest_categorical(name, list(values))
            if chosen is None:
                raise TypeError(f"{name}: None is not a supported choice value")
            return chosen
        case _:
            raise TypeError(f"unsupported parameter: {param!r}")


def tune(
    space: Sequence[Param],
    evaluate: Callable[[dict[str, ParamValue]], float],
    *,
    n_trials: int,
    seed: int = 0,
    warm_start: Sequence[dict[str, ParamValue]] = (),
) -> TuneResult:
    """Maximize ``evaluate`` over ``space`` with a seeded TPE sampler.

    Args:
        space: Parameters to search.
        evaluate: Scores one parameter assignment; higher is better.
        n_trials: Number of evaluations, warm-start points included.
        seed: Sampler seed; the same seed reproduces the same search.
        warm_start: Points evaluated first, so the result is never worse than they are.

    Raises:
        ValueError: If ``n_trials`` is below 1, ``space`` is empty or has duplicate names, or
            ``evaluate`` returns a non-finite score.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    names = [param.name for param in space]
    if not names:
        raise ValueError("search space is empty")
    if len(set(names)) != len(names):
        raise ValueError("duplicate parameter names in search space")

    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    history: list[float] = []

    def objective(trial: optuna.Trial) -> float:
        """Evaluate one trial and record its score."""
        value = float(evaluate({param.name: _suggest(trial, param) for param in space}))
        if not math.isfinite(value):
            raise ValueError(f"evaluate returned a non-finite score: {value}")
        history.append(value)
        return value

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    for point in warm_start:
        study.enqueue_trial(point)
    study.optimize(objective, n_trials=n_trials)
    return TuneResult(
        best_params=dict(study.best_params),
        best_value=float(study.best_value),
        history=tuple(history),
    )
