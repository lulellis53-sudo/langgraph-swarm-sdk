# Forecast engine: pluggable models, polars-first (design)

Date: 2026-10-06 | Branch: `feat/prediction-engine` | Status: draft for review

## Goal
Turn `Prediction/engine.py` (LightGBM-only, pandas-only) into a generic time-series engine with pluggable models and polars-first data handling on a Py3.14 stack. Public API stays compatible: `ForecastConfig`, `ForecastEngine`, `ForecastError`, `REQUIRED_COLUMNS`.

## Non-goals
Deep-learning models, hierarchical reconciliation, new storage backends, changes to `LanceForecastStore`, RTX/BR price logic.

## Assumptions (correct me)
- "2026 imports" = modern libraries and Py3.14 idioms (PEP 695/649, `@override`, `Self`), not a version-pinning exercise.
- Input stays long format: `unique_id`, `ds`, `y`.
- Default behavior (`model="lgbm"`) is unchanged, pinned by `tests/test_prediction_engine.py`.

## Components
| Unit | Purpose | Depends on |
| --- | --- | --- |
| `frame.py` | Accept polars or pandas, validate, normalise to polars; convert to pandas only at library boundaries | polars (core), pandas (lazy) |
| `models.py` | `Forecaster` Protocol; `LGBMForecaster` (existing logic moved), `SeasonalNaive` (numpy), `StatsForecaster` (statsforecast AutoETS/Theta, optional) | frame, metrics |
| `metrics.py` | MAE, RMSE, sMAPE, MASE (numpy) | numpy |
| `engine.py` | `ForecastEngine` selects model from `ForecastConfig.model`, optional mean ensemble | models |

`type ModelName = Literal["lgbm", "seasonal_naive", "stats"]`. Unknown names raise `ForecastError`.

## Data flow
input frame -> `frame.normalise` (validate; polars) -> model `fit` -> `predict(horizon)` returns long frame (`unique_id`, `ds`, model column) -> output in the caller's frame type. Backtest: rolling-origin windows; metrics per series and aggregate; window sizing reuses `min_rows_for_backtest`.

## Errors
Domain errors raise `ForecastError` (missing columns, NaN in `y`, duplicate keys, too-short series, unfitted engine, unknown model, missing optional extra with the `uv sync --extra ...` hint). Original cause kept with `raise ... from`.

## Dependencies
No new core deps. `statsforecast` goes under the existing `forecast` extra only after confirming its current version and macOS x86_64 wheel availability; if unavailable, `stats` is dropped from this scope and reported.

## Testing
- Existing `tests/test_prediction_engine.py` stays green (behavior pin).
- New `tests/test_forecast_models.py`: protocol conformance per model; polars vs pandas input give equal forecasts; SeasonalNaive and metrics known-answer cases; validation errors; empty and one-row series; non-ASCII `unique_id`.
- Gate: `uv run ruff check Prediction tests`, `uv run ty check Prediction`, CLI `backtest` end to end.

## Style
`from __future__ import annotations` first in new modules (project AGENTS.md; overrides the global 3.14 note), lite static template layout, heavy imports inside functions, no import-time side effects.

## Rollback
Separate commits on `feat/prediction-engine` (only when asked); `git restore Prediction/` or revert.
