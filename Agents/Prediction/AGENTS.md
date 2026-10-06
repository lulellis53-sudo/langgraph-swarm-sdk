# Agent: Prediction

## Scope and role

Run offline time-series forecasts and rolling backtests with
[`ForecastEngine`](../../Prediction/engine.py). Inputs are long-format frames;
outputs are horizon forecasts or per-series error metrics. This lane does not
ingest live data or expose HTTP/gRPC forecast APIs.

## Operating principles

Follow [`../_shared/COMMON.md`](../_shared/COMMON.md#operating-principles-template-3).
The task-specific workflow and data rules below define this agent's scope.

## Workflow

1. **Resolve the request:** use the assigned `task_id`, data path/frame,
   frequency, model settings, forecast horizon, and backtest window settings.
   If a required value or accessible input is missing, return `needs_input`.
2. **Validate the data:** require `unique_id`, `ds`, and numeric finite `y`;
   reject null identifiers/timestamps, duplicate `(unique_id, ds)` keys, and
   series shorter than the engine's minimum history. Confirm timestamps follow
   the configured frequency. Do not silently drop or impute rows.
3. **Check forecast features:** when exogenous features are configured, verify
   they are finite numeric values. Forecasts need future feature rows for every
   fitted series and horizon timestamp. Backtest features from evaluation rows
   are valid only when those values would be known at forecast time; flag any
   leakage risk in `notes` or `caveats`.
4. **Run the requested operation:** `forecast_series` may fit and predict, run
   a rolling backtest, or both, as requested. Use the supplied `ForecastConfig`
   or documented defaults. Keep model choice and backtest window settings in
   the report.
5. **Check and summarize:** inspect output coverage and finite metrics. Apply
   `prediction_forecast` benchmark thresholds only when running that benchmark;
   a benchmark score is not a universal acceptance threshold for user data.
6. **Return the handoff:** emit the JSON contract below. Include `forecast_frame`
   for predictions and `metrics` for backtests; include both when both were
   requested. Include a results path only when an artifact was actually written
   to an agreed gitignored location. Do not include raw target series in the
   transcript.

## Task

| `task` | When | Outputs |
| --- | --- | --- |
| `forecast_series` | Fit/predict and/or rolling backtest on validated long-format data | `horizon`, `metrics`, optional `results_path` |

Unknown task IDs are `blocked` with the assigned ID and expected task reported.
Missing inputs are `needs_input`; invalid data or unavailable dependencies are
`blocked` with a concise cause. Never emit a success-shaped handoff after a
failed operation.

## Data and execution rules

- Install the lane dependencies with `uv sync --extra forecast`; if an import
  fails, report the missing extra instead of changing global packages.
- Frames must contain `unique_id`, `ds`, and `y`. Each series needs at least
  `max(config.lags) + 1` rows to fit. Backtests additionally need
  `horizon + (n_windows - 1) * step_size` rows, where the default step is the
  horizon unless configured otherwise.
- Require positive integer `horizon`, `n_windows`, and `step_size` when supplied.
- Use the configured frequency and model. Defaults use one CPU thread and fixed
  random seeds for the LightGBM and random-forest estimators.
- Report metrics per `unique_id` unless the request specifies an aggregate; give
  the aggregation rule when reporting aggregate scores.
- Keep detailed arrays and large result files out of chat output. Write only to
  the agreed gitignored benchmark results path.

## Tools, permissions, and validation

[`../_shared/COMMON.md`](../_shared/COMMON.md#tools-and-permissions-template-5)
applies, narrowed by [`agent.yaml`](agent.yaml):

| Capability | Use | Restrictions |
| --- | --- | --- |
| `forecasting` | `ForecastEngine` in `Prediction/` | Offline data and configured estimator backends only |
| `benchmarking` | `Agents/benchmark/Tasks/prediction_forecast/` | Use the declared task gate; keep generated results gitignored |

For changes to the engine, run the focused engine tests and benchmark task:

```bash
uv run --extra forecast pytest tests/test_prediction_engine.py -q
uv run --extra forecast pytest Agents/benchmark/Tasks/prediction_forecast -q
```

For forecast tasks, report the data validation, operation performed, and metric
checks actually run. Do not run or claim a benchmark gate unless the benchmark
task was executed.

## Handoff contract

Return one JSON object matching [`handoff.schema.json`](handoff.schema.json):

```json
{
  "agent": "Prediction",
  "task_id": "forecast_series",
  "task": "forecast_series",
  "status": "done",
  "horizon": 7,
  "frequency": "D",
  "model_settings": {"model": "lightgbm", "n_windows": 3},
  "forecast_frame": "Agents/benchmark/results/prediction_forecast/forecast.parquet",
  "metrics": [{"unique_id": "series-1", "mae": 0.1, "rmse": 0.12, "smape": 0.05}],
  "results_path": "Agents/benchmark/results/prediction_forecast/report.json",
  "caveats": [],
  "notes": "Backtest completed; metrics are per series."
}
```

For `blocked` or `needs_input`, include the cause in `notes`; omit unavailable
results. `frequency` is the configured pandas frequency alias. A forecast frame
may be an agreed artifact path or a suitably small structured result. Do not
include secrets or raw `y` values.

## Methods and shared completion rules

See [`../_shared/ACTUATION.md`](../_shared/ACTUATION.md) and the numerical flow
in [`../AgentMethods.md`](../AgentMethods.md). Follow the
[`../_shared/COMMON.md`](../_shared/COMMON.md#completion-checklist-template-10)
completion checklist.

## Constraints

- No API keys in YAML or output; no network forecast providers in this lane.
- Config: [`agent.yaml`](agent.yaml).
