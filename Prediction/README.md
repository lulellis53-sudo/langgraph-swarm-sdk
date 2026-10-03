# Prediction — forecasting engine

Global LightGBM and scikit-learn Random Forest models use [Nixtla MLForecast](https://nixtlaverse.nixtla.io/mlforecast/).
Prophet is fitted independently per series. Inputs use long-format time-series data.

## Install

```bash
uv sync --extra forecast
```

## Data schema

| Column | Type | Description |
| :--- | :--- | :--- |
| `unique_id` | string | Series identifier |
| `ds` | datetime | Timestamp (regular frequency per `ForecastConfig.freq`) |
| `y` | float | Target |

Each series must have non-null IDs and timestamps, unique timestamps, numeric finite targets,
and enough observations for the configured lags. Timestamps must be compatible datetimes;
the input must follow the regular frequency declared by `ForecastConfig.freq`.

## Minimal usage

```python
import pandas as pd
from Prediction import ForecastEngine

df = pd.read_csv("series.csv", parse_dates=["ds"])
engine = ForecastEngine().fit(df)
forecast = engine.predict(horizon=7)
metrics = engine.backtest(df, horizon=7, n_windows=2)
```

`ForecastConfig` supports MLForecast lag transforms and a default backtest `step_size`.
Pass `step_size` to `backtest` to override that default. The minimum required history is
`max(lags) + 1` rows for fitting and `max(lags) + 1 + horizon + (n_windows - 1) * step_size`
rows per series for backtesting.

## Models and tabular formats

Select a backend with `ForecastConfig(model="sklearn-random-forest")` or
`ForecastConfig(model="prophet")`; all estimators run on CPU. Configure each estimator
with its own `lightgbm_params`, `random_forest_params` or `prophet_params` dictionary.
Prophet fits one model per series. Symbolic MAE, RMSE and
sMAPE formulas are available from `ForecastEngine.metric_equations()`.

`fit` and `backtest` accept pandas or Polars frames. `predict` and `backtest` accept
`output="pandas"` (default), `output="polars"` or `output="arrow"`. PyArrow provides the
Arrow conversion path.

## Text tokenization and sentence embeddings

`TextFeatureTransformer` provides lazy-loaded tokenization and sentence vectors:

```python
from Prediction import TextFeatureConfig, TextFeatureTransformer

features = TextFeatureTransformer(TextFeatureConfig(backend="fastembed"))
tokens = features.tokenize(["quarterly revenue rose"])
vectors = features.transform(["quarterly revenue rose"])
```

To use text vectors as regressors, join them to training observations by row, then declare
the generated columns. Pass equivalent known future vectors aligned to every forecast
`unique_id` and `ds`:

```python
from Prediction import ForecastConfig, ForecastEngine, TextFeatureTransformer

transformer = TextFeatureTransformer()
train = transformer.attach(train, text_column="description")
feature_columns = tuple(c for c in train.columns if c.startswith("text_embedding_"))
engine = ForecastEngine(ForecastConfig(exogenous_features=feature_columns)).fit(train)
future = transformer.attach(future_text_rows, text_column="description")
forecast = engine.predict(7, future_features=future)
```

The exogenous features must be numeric and finite. Every fitted series needs one known
feature row for each future timestamp at the configured frequency. Backtests use the
provided full frame's features, including evaluation-window rows, so only use covariates
that would actually be known at forecast time.

Use `backend="transformers"` for SentenceTransformers on CPU or `backend="onnx"` for
its ONNX Runtime backend. FastEmbed also uses ONNX Runtime. Model downloads happen when
the transformer is first used. These embedding vectors are standalone features; this
release does not automatically join them to the time-series estimator. On Intel macOS,
the documented ONNX Runtime wheel limitation may make FastEmbed unavailable. The
Radeon OpenCL path accelerates vector math elsewhere in the SDK, not these estimators or
ONNX inference.

## Dependencies

The `forecast` extra includes MLForecast, LightGBM, Prophet, scikit-learn, SymPy, pandas, Polars,
PyArrow, Transformers, SentenceTransformers and tokenizers. GPU compute for these model
backends is not enabled by this extra.

### Prophet cost

Rolling Prophet backtests fit one model per series per window; the full workflow therefore
performs `series_count × (1 + n_windows)` model fits, including the final fit used for
forecasting. Measure wall time on your data and machine with:

```bash
uv run --extra forecast python -m Prediction.benchmark_prophet \
  --series 1 5 20 --observations 180 --horizon 14 --windows 1 3 5
```

The unit suite checks this fit-count scaling deterministically. Benchmark output is local
and workload-specific; there is no universal timing claim.

## Lane development

Work on branch `feat/prediction-engine` in the sibling worktree `../Swarm-Prediction` (see root `README.md`).

```bash
uv run --extra forecast pytest tests/test_prediction_engine.py -q
```
