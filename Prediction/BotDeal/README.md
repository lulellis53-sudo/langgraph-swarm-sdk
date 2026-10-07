# BotDeal lane

Deal-hunting stack (PromoDeals MCP, SQLite offers store, WebSearch harvest) lives
under `Prediction/` and is grouped here for agents and a **synced worktree**.

| Path | Role |
| --- | --- |
| `Prediction/br_hardware.py` | Catalog, floors, alerts, SKU forecasts |
| `Prediction/harvest.py` | Live price harvest |
| `Prediction/ingest.py` | Vector ingest + graphs |
| `Prediction/mcp_server.py` | `promodeals_mcp` tools |
| `Prediction/BotDeal/` | Lane façade + worktree sync |

Parent forecast engine: `Prediction/engine.py` on branch `feat/prediction-engine`
(`../Swarm-Prediction`).

## Worktree (feat/botdeal)

BotDeal uses a **fourth worktree** sibling to Swarm-Prediction, branched from
the prediction engine and merged forward on demand:

| Path | Branch |
| --- | --- |
| `/Users/usuario/BotDeal` | `feat/botdeal` |

### One-time setup + sync from prediction engine

From repo root (`~/Swarm`):

```bash
./Prediction/BotDeal/sync_worktree.sh
```

Or manually:

```bash
cd ~/Swarm
git fetch origin
git branch -f feat/botdeal feat/prediction-engine   # first time only
git worktree add ../BotDeal feat/botdeal             # skip if ../BotDeal exists
git -C ../BotDeal merge feat/prediction-engine -m "sync: prediction-engine -> botdeal"
```

Work in `~/BotDeal`; merge `feat/prediction-engine` into `feat/botdeal` whenever
the forecast lane moves. Push `feat/botdeal` when the deal lane is ready to share.

## Commands

```bash
uv run --project ~/Swarm-Prediction python -m Prediction.BotDeal mcp
uv run --project ~/Swarm-Prediction python -m Prediction.BotDeal harvest
uv run --project ~/Swarm-Prediction python -m Prediction.BotDeal hardware init
```

Environment: `PROMODEALS_DB` (default `Prediction/offers.db`).
