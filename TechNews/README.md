# TechNews

TechNews pipeline: scrape, store, predict, newsletter, humanize, site.

## Trend prediction

The `technews.prediction` package turns stored article counts into short-horizon
trend forecasts: a SQLite `FeatureStore` keeps daily per-category article counts
(`DailyCount` rows), `build_frame` reshapes them into a pandas long frame, and
`TrendForecaster` fits per-category volume series (LightGBM via the root dev
environment, with an offline linear fallback) to emit `ForecastPoint`
predictions and a ranked `movers` list. The `TECHNEWS_DB` environment variable
points the MCP server at the feature store; it exposes the tools
`forecast_categories`, `top_movers`, `search_topic_signal` and
`refresh_features`.

```console
uv run python -m technews.prediction backfill --db features.db --articles articles.db
uv run python -m technews.prediction forecast --db features.db --horizon 7
uv run python -m technews.prediction movers --db features.db
```
