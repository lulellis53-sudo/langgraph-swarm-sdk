# Prediction — offline forecasting lane

Global LightGBM time-series forecasts via [mlforecast](https://github.com/nixtla/mlforecast).
Long-format input only: columns **`unique_id`**, **`ds`**, **`y`**.

## Install

```bash
uv sync --extra forecast
```

Optional lane worktree: `../Swarm-Prediction` on branch `feat/prediction-engine`.

## Minimal example

```python
from Prediction import ForecastConfig, ForecastEngine
import pandas as pd

df = pd.read_csv("series.csv")  # unique_id, ds, y
engine = ForecastEngine(ForecastConfig(freq="D", lags=(1, 7))).fit(df)
forecast = engine.predict(horizon=14)
metrics = engine.backtest(df, horizon=7, n_windows=3)
```

## API

| Symbol | Role |
| --- | --- |
| `ForecastConfig` | `freq`, `lags`, `date_features`, `lgbm_params`, optional `step_size`, `lag_transforms` |
| `ForecastEngine` | `fit`, `predict`, `backtest` |
| `ForecastError` | Invalid data or unfitted engine |

## Tests

```bash
uv run --extra forecast pytest tests/test_prediction_engine.py -q
uv run --extra forecast pytest Agents/benchmark/Tasks/prediction_forecast -q
```

Results artifacts (optional): `Agents/benchmark/results/prediction_forecast/` (gitignored).
