# Cursor lane: Prediction

You work in the **Prediction worktree** (`../Swarm-Prediction` on branch `feat/prediction-engine`).

## Modus operandi

Think → Check (read `Prediction/engine.py`, tests, `pyproject.toml` forecast extra) → analyse → write → **Context7** for `mlforecast` / LightGBM flags → tighten → re-check.

## May edit

- `Prediction/**`
- Root-repo copies of the same paths when checked out on `feat/prediction-engine` (prefer the worktree)
- `tests/test_prediction_engine.py`
- Root `pyproject.toml` `[project.optional-dependencies] forecast` and root `uv.lock` **only on this branch**

## Do not edit

- `WebSearch/**`, `Newsletter/**`
- `src/swarm_sdk/**` refactors unrelated to forecast integration
- Model registry / `Agents/ModelDelegate/` (main/integration lane)

## Quality gate

```bash
cd ../Swarm-Prediction && uv run --extra forecast pytest tests/test_prediction_engine.py -q
```

From repo root when on `feat/prediction-engine`:

```bash
uv run --extra forecast pytest tests/test_prediction_engine.py -q
```

## Git

Stay on `feat/prediction-engine`. Do not create branches or worktrees. See [`.cursor/rules/git-docs.mdc`](../rules/git-docs.mdc).
