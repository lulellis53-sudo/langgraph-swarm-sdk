# BotDeal runbook — one run across the three worktrees

The chain is **WebSearch → BotDeal → Prediction**, driven by a single command.
This directory (`~/Myworkspace/BotDeal`) is the canonical home for `Prediction/`.

## Layout and why it is split

| Worktree | Branch | Owns |
|---|---|---|
| `~/Myworkspace/Swarm-WebSearch` | `feature/websearch` | the `WebSearch` package: providers, fan-out, fetch stack, politeness, extractors |
| `~/Myworkspace/BotDeal` | `feat/botdeal` | `Prediction/` — the hardware catalog, the pipeline, the run driver, `br_hardware` |
| `~/Myworkspace/Swarm-Prediction` | `feat/prediction-engine` | the forecasting engine with dependencies installed |

`Prediction.BotDeal.pipeline` and `...run` import `WebSearch.*`, so `WebSearch`
must be importable. It currently resolves through the symlink
`BotDeal/WebSearch -> ../Swarm/WebSearch` (the stale 1.31 GB checkout inside the
main Swarm worktree). Verify where it points before trusting a run:

```bash
cd ~/Myworkspace/BotDeal
./.venv/bin/python -c "import WebSearch, inspect; print(inspect.getfile(WebSearch))"
```

## Which interpreter to use

**`~/Myworkspace/BotDeal/.venv` cannot forecast**: it has neither `lightgbm` nor
`pandas`, so every forecast records `unavailable / no forecast engine`.
`~/Myworkspace/Swarm-Prediction/.venv` is the only venv with both. Until the
BotDeal venv is synced, run with `PYTHONPATH` pointed at the canonical code and
the Prediction venv as the interpreter:

```bash
cd ~/Myworkspace/BotDeal
PYTHONPATH="$HOME/BotDeal" ~/Myworkspace/Swarm-Prediction/.venv/bin/python \
  -m Prediction.BotDeal run --lookback-days 7
```

To make the BotDeal venv self-sufficient instead:

```bash
cd ~/Myworkspace/BotDeal && uv sync --extra dev --extra forecast
```

## The run command

```bash
cd ~/Myworkspace/BotDeal
PYTHONPATH="$HOME/BotDeal" ~/Myworkspace/Swarm-Prediction/.venv/bin/python \
  -m Prediction.BotDeal run \
    --db offers.db \
    --lookback-days 7 \
    --horizon 7 \
    --limit 10 \
    --scrape-top 3
```

Useful flags:

| Flag | Meaning |
|---|---|
| `--lookback-days N` | Search window reaching back N days. **Must be long enough that successive runs overlap**, or no SKU ever accumulates the 14 observed floors a forecast needs. |
| `--sku SKU` | Restrict to one SKU (repeatable). Default: whole catalog (23 SKUs × 12 sources). |
| `--dry-run` | Print the queries a real run would issue. No network, no writes. |
| `--json` | Emit the report as JSON. |
| `--horizon N` | Forecast horizon in days. |

Or via the lane entry point: `python -m Prediction.BotDeal run --lookback-days 7`.

## What each run records

Every run writes one row to `runs` and prints a delta against the previous run
(`12 (+3)`, `17 (=)`), so a run is comparable rather than anonymous:

```
=== run 2 · 2026-10-07 · lookback 7d ===
  status              : ok
  queries             : 552 (=)
  observations        : 1 (+1)
  floors / alerts     : 17 / 0
  forecasts           : 1 ready, 0 unavailable
  scored vs actual    : 1 forecasts, MAPE 0.58%
```

`forecast_scores` compares each past forecast with the floor actually observed
later, so successive runs accumulate a measured accuracy record instead of
unverifiable point values.

## Why the pipeline used to produce nothing

Three independent blockers, all fixed:

1. `write_forecast` read `payment = 'pix'` while every writer writes `card`, so
   it always found zero rows. It now takes the payment series from
   `forecastable_payments()`.
2. The query window was a single day (`after:<today> before:<tomorrow>`) and
   never overlapped, so a 14-day series was unreachable. Now a rolling lookback.
3. `forecastable_payments`/`write_forecast` assumed a gap-free daily series.
   Real data always has gaps (days with no listing), which crashed mlforecast.
   The series is now reindexed onto a daily calendar and carried forward.

## Database migration

`_SCHEMA` is applied on every `connect()`, then `migrate()` runs and is
idempotent (guarded by existence checks). It:

- adds `predictions.run_id`;
- renames SKUs that changed in `hardware.yaml`
  (`ddr5-16gb/32gb/64gb` → `ddr5-1x16gb/1x32gb/1x64gb`) so older observations
  keep contributing instead of being orphaned;
- stamps `PRAGMA user_version = 1` (it was `0` in every earlier revision).

Backups of all three databases were taken to
`~/Myworkspace/.audit-backups/` before the first migration.

## Scheduled runs

The run is idempotent (observations use `INSERT OR IGNORE` against a UNIQUE
constraint), so a cron/launchd entry is safe. Once daily, after the market day
starts in São Paulo:

```cron
15 9 * * * cd $HOME/Myworkspace/BotDeal && PYTHONPATH=$HOME/BotDeal \
  $HOME/Myworkspace/Swarm-Prediction/.venv/bin/python -m Prediction.BotDeal run \
  --lookback-days 7 >> $HOME/Myworkspace/BotDeal/run.log 2>&1
```

Keep `--lookback-days` at least 7 so consecutive runs overlap. A 14-day window is
safer: `FORECAST_MIN_DAYS = 14` counts distinct floor days, and gaps are normal.
