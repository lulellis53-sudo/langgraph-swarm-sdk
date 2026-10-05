# Offline Tuning Harness (Optuna) + Prompt-Routing Tuner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, offline hyperparameter-search harness and use it to tune the AGENTS.md prompt-routing index against a labeled benchmark, all in a separate git worktree, committing only when tests pass.

**Architecture:** `swarm_sdk.tuning.study.tune` wraps Optuna's seeded TPE sampler behind small typed param classes (in-memory, no files, no network). `swarm_sdk.tuning.routing` scores `AgentPromptIndex` variants (top-1 agent accuracy and recall@k) on labeled prompts and tunes `IndexParams`, reporting a held-out split. A `Tuner` specialist (AGENTS.md + agent.yaml) is registered so the Orchestrator can delegate tuning jobs.

**Tech Stack:** Python >=3.14.5, uv, Optuna >=4 (resolves to 5.0.0 here), pytest, ruff, ty, existing `swarm_sdk` retrieval/memory modules.

**Spec:** No spec file exists. Requirements are the user's request ("make all those changes in another worktree and test, if success commit") and the ideas list from the "Ideias?" turn, narrowed by the feasibility findings below.

## Feasibility findings (verified 2026-10-04 on this machine)

- **Ax cannot be installed here.** `uv pip compile` for `ax-platform>=1.3` with `--python-platform x86_64-apple-darwin` fails: `botorch>=0.18.1` needs `torch>=2.4`, and torch has no macOS x86_64 wheels at that version (torch 2.14.1 ships only for arm64, Linux and Windows; the same failure occurs with Python 3.13). The project is Intel-Mac, Python 3.14.
- **Optuna 5.0.0 resolves** on the same platform (numpy, sqlalchemy, alembic, colorlog, tqdm, pyyaml; no torch). It is the backend used here.
- **JEV tuning is dropped.** `JevRouter._local_evaluate_score` picks the tier from regex hits; its numeric constants (0.78, 0.03, 0.30, 0.05, 0.55) change only the reported score, never the tier. Nothing to optimize.
- **Fallback-order / think-level tuning and per-task agent selection are deferred.** They need recorded per-model quality and cost data that does not exist; tuning on scripted models would fit nothing.
- **Worktree rule.** `.cursor/skills/multi-lane-worktrees/SKILL.md` says not to add worktrees. The user's explicit instruction overrides it for this branch only; the four existing lanes are untouched.
- **Baseline is not fully green at HEAD (`da4b209`).** `Agents/coordination.yaml` references `Agents/Toolchain/agent.yaml`, which does not exist, so `test_config.py::test_agent_manifests_and_coordination` fails. `test_vault.py::test_env_example_lists_only_names` also failed in the working tree. Both are pre-existing and out of scope.

## Global Constraints

- Python `>=3.14.5`; ruff `line-length = 100`, target py314.
- Every new or changed function in `src/` has a one-line imperative docstring ending in a period and full annotations (parameters and return); no `typing.List`/`Optional`, no quoted forward references.
- Tests are offline: no network, no real credentials. The autouse `_isolate_secrets` fixture in `Agents/benchmark/conftest.py` must stay in force.
- No `# noqa`, `# type: ignore`, skip or xfail without a named rule and reason.
- Never print, log or commit secret values. If a key-shaped token appears anywhere, stop and report file and line only.
- Run commands through this shell function (zsh does not word-split a variable holding the flags):
  ```bash
  u() { uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 --extra tune "$@"; }
  ```
  (`--extra tune` exists only after Task 1 Step 3; before that, drop it.)
- Work only in `/Users/usuario/Swarm-Tuning` on branch `feat/tuning-optuna`. Commit there only after the task's tests pass. Never push, never `--no-verify`, never force.
- **Success means:** every new test passes, no test outside the two known pre-existing failures fails, and `ruff check` reports no finding that is not already in the baseline.

## Review Focus

- `evaluate` returns NaN or infinity: the study must raise `ValueError`, not crown a bogus "best" trial. (Task 1)
- Same seed twice: identical best parameters and history, so results are reproducible. (Task 1)
- The harness must not leave files behind (no Optuna SQLite journal) in the working directory. (Task 1)
- Accented (Portuguese) prompts: `função` must tokenize to one word `funcao`, not fragments. Cross-language matching (Portuguese prompt against English AGENTS.md) is NOT solved by this plan; it needs a multilingual embedder via `--extra embed`. (Task 2)
- Too few cases, an empty file, a missing key, or a label naming an agent that does not exist: a clear `ValueError`, not `ZeroDivisionError` or a silent zero score. (Task 3)

---

### Task 0: Create the worktree and carry over the uncommitted work

The prompt-index, redaction and key-isolation files from the previous turn exist only as uncommitted changes in `/Users/usuario/Swarm`. Tasks 2-3 build on them, so they become the first commit on the new branch.

**Files:**
- Copy into worktree (unchanged): `Agents/benchmark/conftest.py`, `Agents/benchmark/tests/test_server_graphs.py`, `Agents/benchmark/tests/test_all_models.py`, `Agents/benchmark/tests/test_prompt_index.py`, `Agents/benchmark/tests/test_secret_isolation.py`, `src/swarm_sdk/agents/prompt_index.py`, `src/swarm_sdk/redact.py`, `docs/superpowers/plans/2026-10-04-optuna-tuning.md`

**Interfaces:**
- Produces: worktree `/Users/usuario/Swarm-Tuning` on `feat/tuning-optuna`; `AgentPromptIndex`, `CorpusTfidfEmbedder`, `improve_prompt`, `redact_secrets` available to later tasks.

- [ ] **Step 1: Confirm the worktree and branch do not exist**

```bash
cd /Users/usuario/Swarm
git worktree list
git branch --list feat/tuning-optuna
ls -d ../Swarm-Tuning 2>&1 | head -1
```
Expected: no `Swarm-Tuning` row, empty branch list, `No such file or directory`. If any exists, stop and report.

- [ ] **Step 2: Create the worktree from the current commit**

```bash
git worktree add -b feat/tuning-optuna ../Swarm-Tuning HEAD
git -C ../Swarm-Tuning log --oneline -1
```
Expected: the same commit as `git log --oneline -1` in the root tree.

- [ ] **Step 3: Copy the eight files**

```bash
for f in Agents/benchmark/conftest.py Agents/benchmark/tests/test_server_graphs.py \
  Agents/benchmark/tests/test_all_models.py Agents/benchmark/tests/test_prompt_index.py \
  Agents/benchmark/tests/test_secret_isolation.py src/swarm_sdk/agents/prompt_index.py \
  src/swarm_sdk/redact.py docs/superpowers/plans/2026-10-04-optuna-tuning.md; do
  mkdir -p "../Swarm-Tuning/$(dirname "$f")" && cp "$f" "../Swarm-Tuning/$f"
done
git -C ../Swarm-Tuning status --short
git -C ../Swarm-Tuning diff --stat -- Agents/benchmark/conftest.py Agents/benchmark/tests/test_server_graphs.py
```
Expected: two ` M` entries (conftest +15, test_server_graphs +3/-1 or similar) and six `??` entries. If either modified file shows a larger diff, the root copy contained unrelated edits: stop and report.

- [ ] **Step 4: Run the baseline gate in the worktree**

```bash
cd /Users/usuario/Swarm-Tuning
u() { uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 "$@"; }
u pytest Agents/benchmark -q --tb=line -p no:cacheprovider 2>&1 | rg -v 'Warning|warn|set_event' | tail -12
u ruff check src Agents/benchmark Main 2>&1 | tail -3
```
Expected: the only failures are `test_config.py::test_agent_manifests_and_coordination` and possibly `test_vault.py::test_env_example_lists_only_names`. Record the exact list and the ruff count. `test_no_key_shaped_token_in_tracked_files` scans only tracked files, so it also covers HEAD's committed docs: if it reports offenders, print the `path:line` list only and STOP (a committed key-shaped token must be handled by the user, not edited around).

- [ ] **Step 5: Commit the carried-over work, then the plan**

```bash
cd /Users/usuario/Swarm-Tuning
git add Agents/benchmark/conftest.py Agents/benchmark/tests/test_server_graphs.py \
  Agents/benchmark/tests/test_all_models.py Agents/benchmark/tests/test_prompt_index.py \
  Agents/benchmark/tests/test_secret_isolation.py src/swarm_sdk/agents/prompt_index.py src/swarm_sdk/redact.py
git commit -m "feat: add AGENTS.md prompt index, secret redaction and test key isolation

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
git add docs/superpowers/plans/2026-10-04-optuna-tuning.md
git commit -m "docs: add offline tuning plan

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
git log --oneline -3
```
Expected: two new commits on `feat/tuning-optuna`.

---

### Task 1: Tuning harness (`swarm_sdk.tuning`)

**Files:**
- Modify: `pyproject.toml` (add the `tune` extra), `uv.lock`
- Create: `src/swarm_sdk/tuning/__init__.py`, `src/swarm_sdk/tuning/study.py`
- Test: `Agents/benchmark/tests/test_tuning_study.py`

**Interfaces:**
- Produces (used by Task 3):
  - `IntParam(name: str, low: int, high: int)`, `FloatParam(name: str, low: float, high: float, log: bool = False)`, `ChoiceParam(name: str, values: tuple[ParamValue, ...])`
  - `type ParamValue = int | float | str | bool`, `type Param = IntParam | FloatParam | ChoiceParam`
  - `TuneResult(best_params: dict[str, ParamValue], best_value: float, history: tuple[float, ...])`
  - `tune(space: Sequence[Param], evaluate: Callable[[dict[str, ParamValue]], float], *, n_trials: int, seed: int = 0, warm_start: Sequence[dict[str, ParamValue]] = ()) -> TuneResult` (maximizes `evaluate`)

- [ ] **Step 1: Write the failing tests**

`Agents/benchmark/tests/test_tuning_study.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/usuario/Swarm-Tuning
u() { uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 "$@"; }
u pytest Agents/benchmark/tests/test_tuning_study.py -q --tb=line -p no:cacheprovider 2>&1 | tail -4
```
Expected: collection error `ModuleNotFoundError: No module named 'swarm_sdk.tuning'`.

- [ ] **Step 3: Add the optional dependency**

In `pyproject.toml`, inside `[project.optional-dependencies]`, add this line directly before the `jupyter = [` entry:

```toml
tune = ["optuna>=4"]
```

Then:

```bash
uv lock 2>&1 | tail -5
git diff --stat uv.lock | tail -1
rg -n '^name = "(optuna|alembic|colorlog|sqlalchemy)"' uv.lock
```
Expected: `uv.lock` only gains `optuna` and its dependencies; no existing package changes version. If other pins move, run `git checkout uv.lock`, report which packages moved, and stop.

- [ ] **Step 4: Write the implementation**

`src/swarm_sdk/tuning/__init__.py`:

```python
"""Offline hyperparameter search helpers (optional ``tune`` extra)."""

from __future__ import annotations

from swarm_sdk.tuning.study import (
    ChoiceParam,
    FloatParam,
    IntParam,
    Param,
    ParamValue,
    TuneResult,
    tune,
)

__all__ = [
    "ChoiceParam",
    "FloatParam",
    "IntParam",
    "Param",
    "ParamValue",
    "TuneResult",
    "tune",
]
```

`src/swarm_sdk/tuning/study.py`:

```python
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
            return trial.suggest_categorical(name, list(values))
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

    study = optuna.create_study(
        direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed)
    )
    for point in warm_start:
        study.enqueue_trial(point)
    study.optimize(objective, n_trials=n_trials)
    return TuneResult(
        best_params=dict(study.best_params),
        best_value=float(study.best_value),
        history=tuple(history),
    )
```

- [ ] **Step 5: Run the tests and the cheap checks**

```bash
u() { uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 --extra tune "$@"; }
u pytest Agents/benchmark/tests/test_tuning_study.py -q --tb=short -p no:cacheprovider 2>&1 | tail -8
u ruff format src/swarm_sdk/tuning Agents/benchmark/tests/test_tuning_study.py
u ruff check src/swarm_sdk/tuning Agents/benchmark/tests/test_tuning_study.py
u ty check src/swarm_sdk/tuning Agents/benchmark/tests/test_tuning_study.py
u ruff check --target-version py314 --select D,ANN --config 'lint.pydocstyle.convention = "google"' src/swarm_sdk/tuning
```
Expected: all tests pass; the other four commands report no findings. If `test_finds_a_near_optimal_point` fails, raise `n_trials` to 100 in the test; do not lower the `-2.0` threshold. If `ty` rejects the `optuna.Trial` annotation, report the exact message instead of adding an ignore.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/swarm_sdk/tuning Agents/benchmark/tests/test_tuning_study.py
git commit -m "feat: add optional Optuna tuning harness

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Make the prompt index tunable and Unicode-aware

**Files:**
- Modify: `src/swarm_sdk/agents/prompt_index.py`
- Test: `Agents/benchmark/tests/test_prompt_index.py`

**Interfaces:**
- Consumes: existing `AgentPromptIndex.build`, `CorpusTfidfEmbedder.fit`, `RAGIngestionPipeline.chunk_markdown(text, source_file=..., max_chunk_size=...)`.
- Produces (used by Task 3):
  - `IndexParams(max_chunk_size: int = 1500, sublinear_tf: bool = True, name_boost: int = 1, k: int = 4)` (frozen, slots)
  - `AgentPromptIndex.build(agents_dir, *, store=None, embedder=None, params: IndexParams | None = None)`
  - `AgentPromptIndex.size -> int` (number of indexed chunks)
  - `CorpusTfidfEmbedder.fit(texts, dim=_EMBED_DIM, *, sublinear_tf: bool = True)`
  - Defaults reproduce today's behavior exactly (1500-char chunks, sublinear tf, agent name once).

- [ ] **Step 1: Write the failing tests**

Append to `Agents/benchmark/tests/test_prompt_index.py` (add `IndexParams` and `CorpusTfidfEmbedder` to the existing `from swarm_sdk.agents.prompt_index import (...)` list):

```python
def test_embedder_folds_accents_and_keeps_words_whole() -> None:
    embedder = CorpusTfidfEmbedder.fit(["funcao de ordenacao rapida"])
    accented = embedder.embed(["função"])[0]
    plain = embedder.embed(["funcao"])[0]
    assert float(accented @ plain) == pytest.approx(1.0)


def test_smaller_chunks_produce_more_chunks() -> None:
    default = AgentPromptIndex.build(_AGENTS)
    small = AgentPromptIndex.build(_AGENTS, params=IndexParams(max_chunk_size=400))
    assert small.size > default.size


def test_name_boost_zero_still_builds_and_searches() -> None:
    index = AgentPromptIndex.build(_AGENTS, params=IndexParams(name_boost=0, sublinear_tf=False))
    assert index.search("refactor this module", k=2)


def test_default_params_match_the_documented_defaults() -> None:
    assert IndexParams() == IndexParams(
        max_chunk_size=1500, sublinear_tf=True, name_boost=1, k=4
    )
```

- [ ] **Step 2: Run to verify they fail**

```bash
u() { uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 --extra tune "$@"; }
u pytest Agents/benchmark/tests/test_prompt_index.py -q --tb=line -p no:cacheprovider 2>&1 | tail -4
```
Expected: `ImportError: cannot import name 'IndexParams'`.

- [ ] **Step 3: Implement**

Read `src/swarm_sdk/agents/prompt_index.py`, then make exactly these edits.

1. Imports: add `import unicodedata`. Add `"IndexParams"` to `__all__` (keep it sorted).

2. Replace `_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")` with:

```python
_TOKEN_RE = re.compile(r"[^\W_]{2,}")
```

3. Add below the constants:

```python
def _tokens(text: str) -> list[str]:
    """Return lower-cased, accent-folded word tokens of two or more characters."""
    folded = unicodedata.normalize("NFKD", text.casefold())
    return _TOKEN_RE.findall("".join(ch for ch in folded if not unicodedata.combining(ch)))


def _labeled(agent: str, text: str, name_boost: int) -> str:
    """Prefix ``text`` with the agent name repeated ``name_boost`` times."""
    return " ".join([*([agent] * name_boost), text])


@dataclass(frozen=True, slots=True)
class IndexParams:
    """Tunable retrieval knobs; the defaults reproduce the untuned behavior."""

    max_chunk_size: int = 1500
    sublinear_tf: bool = True
    name_boost: int = 1
    k: int = 4
```

4. In `CorpusTfidfEmbedder`: change `__init__` to also take and store `sublinear_tf: bool`; change `fit` to `def fit(cls, texts: Sequence[str], dim: int = _EMBED_DIM, *, sublinear_tf: bool = True) -> Self` building `docs = [set(_tokens(text)) for text in texts]` and returning `cls(dim, idf, math.log(1 + n) + 1.0, sublinear_tf)`; in `embed` replace the loop body with:

```python
            for token, count in Counter(_tokens(text)).items():
                tf = 1.0 + math.log(count) if self._sublinear_tf else float(count)
                row[zlib.crc32(token.encode()) % self.dim] += tf * self._idf.get(
                    token, self._default_idf
                )
```

5. In `AgentPromptIndex.__init__` add `self._params = IndexParams()`; add the property:

```python
    @property
    def size(self) -> int:
        """Number of indexed chunks."""
        return len(self._meta)
```

6. In `build`: add parameter `params: IndexParams | None = None` (document it in Args: "Retrieval knobs; defaults to ``IndexParams()``."), set `params = params or IndexParams()` at the top, pass `max_chunk_size=params.max_chunk_size` to `chunker.chunk_markdown(...)`, build the fit corpus with `_labeled(a, t, params.name_boost)` and `sublinear_tf=params.sublinear_tf`, store `index._params = params` and `index._name_boost = params.name_boost`, and in `_add` replace `labeled = f"{agent} {text}"` with `labeled = _labeled(agent, text, self._name_boost)`. Initialize `self._name_boost = 1` in `__init__`.

- [ ] **Step 4: Run tests and checks**

```bash
u() { uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 --extra tune "$@"; }
u pytest Agents/benchmark/tests/test_prompt_index.py -q --tb=short -p no:cacheprovider 2>&1 | tail -6
u ruff format src/swarm_sdk/agents/prompt_index.py Agents/benchmark/tests/test_prompt_index.py
u ruff check src/swarm_sdk/agents/prompt_index.py Agents/benchmark/tests/test_prompt_index.py
u ty check src/swarm_sdk/agents/prompt_index.py
u ruff check --target-version py314 --select D,ANN --config 'lint.pydocstyle.convention = "google"' src/swarm_sdk/agents/prompt_index.py
```
Expected: all tests pass (including the pre-existing persona-retrieval test, which proves defaults are unchanged); no findings.

- [ ] **Step 5: Commit**

```bash
git add src/swarm_sdk/agents/prompt_index.py Agents/benchmark/tests/test_prompt_index.py
git commit -m "feat: make prompt index tunable and accent-aware

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Routing benchmark and tuner

**Files:**
- Create: `Agents/benchmark/Tasks/routing/cases.json`, `src/swarm_sdk/tuning/routing.py`
- Test: `Agents/benchmark/tests/test_tuning_routing.py`

**Interfaces:**
- Consumes: Task 1 `tune`, `IntParam`, `ChoiceParam`, `ParamValue`; Task 2 `IndexParams`, `AgentPromptIndex.build(..., params=)`, `.search`, `.agents`.
- Produces:
  - `RoutingCase(prompt: str, agent: str)`
  - `RoutingScore(top1: float, recall_at_k: float, n: int)` with property `objective -> float` (= `top1 + 0.1 * recall_at_k`)
  - `load_cases(path: Path) -> list[RoutingCase]`
  - `score_routing(index: AgentPromptIndex, cases: Sequence[RoutingCase], k: int) -> RoutingScore`
  - `split_cases(cases: Sequence[RoutingCase]) -> tuple[list[RoutingCase], list[RoutingCase]]` (even indexes train, odd hold-out)
  - `RoutingTuning(best: IndexParams, baseline_train: RoutingScore, best_train: RoutingScore, baseline_holdout: RoutingScore, best_holdout: RoutingScore)`
  - `tune_routing(agents_dir: Path, cases: Sequence[RoutingCase], *, n_trials: int, seed: int = 0) -> RoutingTuning`
  - `main(argv: Sequence[str] | None = None) -> int` and `python -m swarm_sdk.tuning.routing`

- [ ] **Step 1: Write the labeled cases**

`Agents/benchmark/Tasks/routing/cases.json` (all labels are directory names under `Agents/`):

```json
[
  {"prompt": "extract this long function into smaller ones without changing behavior", "agent": "Refactor"},
  {"prompt": "write pytest tests for the new parser and run them", "agent": "Tester"},
  {"prompt": "review this pull request diff for bugs and style problems", "agent": "Reviewer"},
  {"prompt": "audit the repository for vulnerabilities and leaked secrets", "agent": "Security"},
  {"prompt": "design a REST endpoint with an OpenAPI schema and versioning", "agent": "ApiDesigner"},
  {"prompt": "convert this plain text file with columns into a CSV", "agent": "TxtToCsv"},
  {"prompt": "set up the Dockerfile and CI pipeline for deployment", "agent": "DevOps"},
  {"prompt": "write the README and docstrings for this module", "agent": "Documenter"},
  {"prompt": "profile the hot loop and reduce its latency", "agent": "Optimizer"},
  {"prompt": "find the root cause of this stack trace and crash", "agent": "Debugger"},
  {"prompt": "fetch this web page url and extract its content", "agent": "WebFetch"},
  {"prompt": "train and evaluate a classification model with cross validation", "agent": "MLSpecialist"},
  {"prompt": "benchmark the two implementations and compare their throughput", "agent": "Benchmarker"},
  {"prompt": "break the goal into a dependency graph of ordered tasks", "agent": "Planner"},
  {"prompt": "implement the new feature in these files", "agent": "Coder"},
  {"prompt": "normalize and deduplicate these records into one common schema", "agent": "Normalizer"},
  {"prompt": "define the module boundaries and overall architecture", "agent": "Architect"},
  {"prompt": "choose which model tier should handle this task", "agent": "ModelDelegate"}
]
```

- [ ] **Step 2: Write the failing tests**

`Agents/benchmark/tests/test_tuning_routing.py`:

```python
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
        tune_routing(
            tiny_agents, [*_tiny_cases(), RoutingCase("x", "Ghost")], n_trials=2
        )
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
```

- [ ] **Step 3: Run to verify they fail**

```bash
u() { uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 --extra tune "$@"; }
u pytest Agents/benchmark/tests/test_tuning_routing.py -q --tb=line -p no:cacheprovider 2>&1 | tail -4
```
Expected: `ModuleNotFoundError: No module named 'swarm_sdk.tuning.routing'`.

- [ ] **Step 4: Implement**

`src/swarm_sdk/tuning/routing.py`:

```python
"""Tune ``AgentPromptIndex`` retrieval knobs against labeled routing prompts."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
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


def score_routing(
    index: AgentPromptIndex, cases: Sequence[RoutingCase], k: int
) -> RoutingScore:
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
        params = IndexParams(**values)  # ty: ignore[invalid-argument-type]
        score = score_routing(AgentPromptIndex.build(agents_dir, params=params), train, params.k)
        return score.objective - _K_PENALTY * params.k

    result = tune(
        _SPACE, evaluate, n_trials=n_trials, seed=seed, warm_start=[asdict(baseline)]
    )
    best = IndexParams(**result.best_params)  # ty: ignore[invalid-argument-type]
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
```

Notes for the implementer: the two `# ty: ignore[invalid-argument-type]` comments name a rule and exist because `ParamValue` is a union that `IndexParams` fields do not accept statically; run `ty check` first and **remove them if `ty` does not flag those lines**. The first `warm_start` value includes `sublinear_tf=True` and `name_boost=1`, which are inside the search space, so the baseline is a valid trial.

- [ ] **Step 5: Run tests and checks**

```bash
u() { uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 --extra tune "$@"; }
u pytest Agents/benchmark/tests/test_tuning_routing.py -q --tb=short -p no:cacheprovider 2>&1 | tail -8
u ruff format src/swarm_sdk/tuning Agents/benchmark/tests/test_tuning_routing.py
u ruff check src/swarm_sdk/tuning Agents/benchmark/tests/test_tuning_routing.py
u ty check src/swarm_sdk/tuning Agents/benchmark/tests/test_tuning_routing.py
u ruff check --target-version py314 --select D,ANN --config 'lint.pydocstyle.convention = "google"' src/swarm_sdk/tuning
```
Expected: pass, no findings. If `test_tune_routing_on_the_real_agents_is_reproducible` takes longer than ~60 s, time one `AgentPromptIndex.build(Path("Agents"))` call and reduce `n_trials` in the test (not the assertions).

- [ ] **Step 6: Run the tuner once and record the numbers**

```bash
u python -m swarm_sdk.tuning.routing --trials 40 --seed 0 | tee /tmp/routing-report.json | head -40
```
Run it from `/Users/usuario/Swarm-Tuning`. Expected: JSON with `best`, and four score blocks. Copy `baseline_*` and `best_*` objectives into the Task 5 report verbatim; if hold-out `best` is worse than hold-out `baseline`, say so (that is overfitting, not a bug). Do not commit the output.

- [ ] **Step 7: Commit**

```bash
git add Agents/benchmark/Tasks/routing/cases.json src/swarm_sdk/tuning/routing.py Agents/benchmark/tests/test_tuning_routing.py
git commit -m "feat: add routing benchmark and retrieval tuner

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `Tuner` specialist, registration and docs

**Files:**
- Create: `Agents/Tuner/AGENTS.md`, `Agents/Tuner/agent.yaml`
- Modify: `Agents/coordination.yaml`, `Agents/SKILLS.md`, `README.md`, `Agents/benchmark/Tasks/routing/cases.json`
- Test: existing `test_config.py::test_agent_manifests_and_coordination`, `test_prompt_index.py`, `test_tuning_routing.py`

**Interfaces:**
- Consumes: `python -m swarm_sdk.tuning.routing` from Task 3.
- Produces: an agent named `Tuner` discoverable by `load_all_agent_manifests` and by `AgentPromptIndex` (its AGENTS.md is indexed automatically).

- [ ] **Step 1: Add a routing case that expects the new agent (failing first)**

Append this object to the list in `Agents/benchmark/Tasks/routing/cases.json` (add a comma after the previous last object):

```json
  {"prompt": "tune the retrieval hyperparameters with a seeded search and report the hold-out score", "agent": "Tuner"}
```

```bash
u() { uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 --extra tune "$@"; }
u pytest Agents/benchmark/tests/test_tuning_routing.py::test_shipped_cases_load_and_name_real_agents -q --tb=line -p no:cacheprovider 2>&1 | tail -3
```
Expected: FAIL (`Tuner` is not an indexed agent yet).

- [ ] **Step 2: Create the agent contract**

`Agents/Tuner/agent.yaml`:

```yaml
version: "1"
name: Tuner
role: offline_parameter_tuning

model: openai:gpt-4o-mini
think_level: medium
effort: medium
api_key_env: OPENAI_API_KEY

token_budget:
  max_prompt: 8192
  max_completion: 2048

tasks:
  - id: define_search
    description: >-
      Pick the parameters to tune, their bounds and one deterministic offline
      benchmark that scores them. Refuse a benchmark that needs live providers.
    outputs:
      - search_space
      - benchmark

  - id: run_study
    description: >-
      Run a seeded study that includes the current defaults as a warm start,
      then report train and hold-out scores for baseline and best.
    outputs:
      - best_params
      - scores

capabilities:
  - code_edit
  - shell
  - test_runner
```

`Agents/Tuner/AGENTS.md`:

````markdown
# Agent: Tuner

## Persona
You are a parameter-tuning specialist. You improve retrieval and routing settings by running small, seeded, offline searches against a labeled benchmark, and you report what was measured, not what was hoped for.

Triggers: tune, tuning, hyperparameters, optimize parameters, grid or Bayesian search, Optuna, hold-out score. Speak in the user's language.

## Responsibilities
- Define a search space with explicit bounds and a single deterministic score
- Run a seeded study that starts from the current defaults
- Report baseline versus best on both the train split and the hold-out split
- Say plainly when tuning overfits (hold-out worse than baseline)

## Scope
Offline parameters of this repository: retrieval chunk size, term weighting, name boost, retrieval depth. You do not call live model providers, spend tokens, or change code behavior beyond the parameters you were asked to tune.

## Behavioral guidelines
1. **Offline and deterministic.** The same seed must reproduce the same result. No network, no keys.
2. **Defaults are trial zero.** The result can never be worse than the current settings on the train split.
3. **Hold-out is the verdict.** Quote the hold-out score next to the train score every time.
4. **Small benchmarks overfit.** With few labeled cases, say how many there are and treat gains as indicative.
5. **No secrets.** Never put credentials in benchmarks, reports or logs.

## Pre-task checklist
- [ ] Locate the benchmark cases and confirm every label exists
- [ ] Run the current defaults and record the baseline
- [ ] Confirm the optional `tune` extra is installed (`uv run --extra tune ...`)

## Workflow
1. Define the search space and objective.
2. Run `uv run --extra tune python -m swarm_sdk.tuning.routing --trials 40 --seed 0`.
3. Compare baseline and best on train and hold-out.
4. Recommend adopting the new defaults only if the hold-out score did not drop.

## What not to do
1. Tuning against live providers or paid APIs.
2. Reporting the train score as the result.
3. Changing the benchmark labels to make a score go up.
4. Adopting parameters that lose on the hold-out split.

## Post-task checklist
- [ ] Baseline and best reported for train and hold-out
- [ ] Seed and trial count stated
- [ ] No behavior change outside the tuned parameters

## Output contract
```json
{
  "agent": "Tuner",
  "task_id": "<assigned task id>",
  "status": "done | blocked | needs_input",
  "search_space": ["<parameter and bounds>"],
  "seed": 0,
  "trials": 40,
  "baseline": {"train": 0.0, "holdout": 0.0},
  "best": {"params": {}, "train": 0.0, "holdout": 0.0},
  "recommendation": "<adopt | keep defaults, with the reason>",
  "notes": "<overfitting risk, number of cases>"
}
```

## Constraints
- Offline only; deterministic given a seed
- Never weaken a benchmark to improve a score
- Config file: [`agent.yaml`](agent.yaml)
````

- [ ] **Step 3: Register the agent**

In `Agents/coordination.yaml`, find the end of the `agents:` list (`rg -n '^[a-z_]+:' Agents/coordination.yaml` shows the next top-level key) and add, with the same indentation as its siblings, immediately after the last agent entry:

```yaml
  - name: Tuner
    role: offline parameter tuning
    contract: Agents/Tuner/AGENTS.md
    manifest: Agents/Tuner/agent.yaml
```

In `Agents/SKILLS.md`, copy the table row format of the `Optimizer` row (`rg -n 'Optimizer' Agents/SKILLS.md`) and add a `Tuner` row with the description "Offline seeded parameter tuning against a labeled benchmark; reports train and hold-out scores", mirroring the other columns' style.

In `README.md`, append (or place next to the other optional-extras docs, found with `rg -n -i 'extra' README.md | head`) this section:

````markdown
## Tuning (optional)

Install the extra and run the routing tuner (offline, seeded, no API keys):

```bash
uv run --extra tune python -m swarm_sdk.tuning.routing --trials 40 --seed 0
```

It reports baseline versus tuned top-1 routing accuracy on a train split and a hold-out split of
`Agents/benchmark/Tasks/routing/cases.json`. Ax is not used: its BoTorch/PyTorch dependency has no
macOS x86_64 wheels.
````

- [ ] **Step 4: Run the checks**

```bash
u() { uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 --extra tune "$@"; }
u pytest Agents/benchmark/tests/test_tuning_routing.py Agents/benchmark/tests/test_prompt_index.py -q --tb=short -p no:cacheprovider 2>&1 | tail -6
u python -m swarm_sdk.agents.validate 2>&1 | tail -5
u pytest Agents/benchmark/tests/test_config.py -q --tb=line -p no:cacheprovider 2>&1 | tail -4
```
Expected: routing and prompt-index tests pass (the new case now resolves, and `index.agents == expected` includes `Tuner`). `validate` may still print only the known `Toolchain` lines; any message mentioning `Tuner` must be fixed. `test_agent_manifests_and_coordination` may still fail for the known `Toolchain` reason only; if its message mentions `Tuner`, fix the entry.

- [ ] **Step 5: Commit**

```bash
git add Agents/Tuner Agents/coordination.yaml Agents/SKILLS.md README.md Agents/benchmark/Tasks/routing/cases.json
git commit -m "feat: add Tuner specialist and tuning docs

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Full gate and report

**Files:** none modified (fix-ups, if any, are committed as `fix:` commits on the same branch).

- [ ] **Step 1: Run the whole gate in the worktree**

```bash
cd /Users/usuario/Swarm-Tuning
u() { uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 --extra tune "$@"; }
u pytest Agents/benchmark -q --tb=line -p no:cacheprovider 2>&1 | rg -v 'Warning|warn|set_event' | tail -8
u ruff check src Agents/benchmark Main 2>&1 | tail -3
u ty check src/swarm_sdk/tuning src/swarm_sdk/agents/prompt_index.py src/swarm_sdk/redact.py
git status --short | head
git log --oneline -8
```
Expected: failures limited to the baseline set recorded in Task 0 Step 4; the ruff count no higher than the baseline; clean working tree; five commits above the base.

- [ ] **Step 2: Decide success**

If every new test passes and nothing outside the baseline failures fails, the work stands as committed. If a new failure appears, diagnose it (read the error, state the cause in one sentence), fix it in a separate `fix:` commit, and re-run; stop after three attempts and report the output.

- [ ] **Step 3: Report**

State: commits made (hashes), the baseline failures that remain, the Task 3 Step 6 numbers (baseline versus best, train and hold-out), what was not run, and the undo: `git worktree remove ../Swarm-Tuning && git branch -D feat/tuning-optuna` (nothing was pushed or merged; the root tree still holds the original uncommitted copies of the carried-over files).
