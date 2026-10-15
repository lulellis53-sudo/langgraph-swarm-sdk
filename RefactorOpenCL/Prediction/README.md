# Prediction — offline forecasting lane

Global LightGBM time-series forecasts via [mlforecast](https://github.com/nixtla/mlforecast).
Long-format input only: columns **`unique_id`**, **`ds`**, **`y`**.

## Install

```bash
uv sync --extra forecast
```

For optional forecast persistence, install `uv sync --extra forecast-lancedb`. Pass a local
path, object-storage URI, or remote LanceDB URI to `LanceForecastStore`. Remote credentials
can be supplied through the environment variable named by `api_key_env` (`LANCEDB_API_KEY`
by default). Each run uses a distinct table; an existing run is never overwritten.

Optional lane worktree: `../Swarm-Prediction` on branch `feat/prediction-engine`.

## CLI

```bash
uv run --extra forecast python -m Prediction.cli backtest series.csv --horizon 7 --json
uv run --extra forecast python -m Prediction.cli predict series.csv --horizon 14 -o forecast.csv
```

## Minimal example

```python
from Prediction import ForecastConfig, ForecastEngine
import pandas as pd

df = pd.read_csv("series.csv")  # unique_id, ds, y
engine = ForecastEngine(ForecastConfig(freq="D", lags=(1, 7))).fit(df)
forecast = engine.predict(horizon=14)
metrics = engine.backtest(df, horizon=7, n_windows=3)

from Prediction import LanceForecastStore
store = LanceForecastStore("./data/forecasts.lance")
run_id = store.append_forecasts(forecast)
saved = store.read_run(run_id, limit=500)
```

## API

| Symbol | Role |
| --- | --- |
| `ForecastConfig` | `freq`, `lags`, `date_features`, `lgbm_params`, optional `step_size`, `lag_transforms` |
| `ForecastEngine` | `fit`, `predict`, `backtest` |
| `ForecastError` | Invalid data or unfitted engine |
| `LanceForecastStore` | Append forecast runs and read bounded run results |

## BotDeal lane (worktree)

PromoDeals / deal bot façade and **synced worktree** on `feat/botdeal`:

```bash
chmod +x Prediction/BotDeal/sync_worktree.sh
./Prediction/BotDeal/sync_worktree.sh   # from ~/Swarm-Prediction (or ~/Swarm)
uv run python -m Prediction.BotDeal mcp
```

See [`BotDeal/README.md`](BotDeal/README.md) (`~/BotDeal` worktree merges `feat/prediction-engine`).

## Offer pipeline (PromoDeals)

Brazilian hardware prices, SQLite store (`Prediction/offers.db`), harvest/ingest CLIs, and MCP server (`Prediction/mcp_server.py`).

```bash
uv run python -m Prediction.br_hardware init
uv run python ~/Swarm-Prediction/Prediction/mcp_server.py
```

| Module | Role |
| --- | --- |
| `br_hardware` | Catalog, floors, alerts, forecasts |
| `harvest` | WebSearch-backed price harvest |
| `ingest` | Vector ingest + graphs |
| `mcp_server` | `promodeals_mcp` tools |

## Tests

```bash
uv run --extra forecast pytest tests/test_prediction_engine.py -q
uv run --extra forecast pytest tests/test_br_hardware.py tests/test_mcp_server.py -q
uv run --extra forecast pytest Agents/benchmark/Tasks/prediction_forecast -q
```

Results artifacts (optional): `Agents/benchmark/results/prediction_forecast/` (gitignored).
