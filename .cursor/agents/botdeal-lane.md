# Cursor lane: BotDeal (Prediction sub-lane)

You work in the **BotDeal worktree** (`../BotDeal` on branch `feat/botdeal`), synced from
`feat/prediction-engine` via `Prediction/BotDeal/sync_worktree.sh`.

## May edit

- `Prediction/BotDeal/**`
- `Prediction/br_hardware.py`, `harvest.py`, `ingest.py`, `mcp_server.py`, `price_multisite.py`
- `tests/test_br_hardware.py`, `tests/test_mcp_server.py`

## Do not edit

- `WebSearch/**` (consume via harvest imports / PYTHONPATH)
- Unrelated `Prediction/engine.py` refactors unless the task spans forecast + deals

## Sync

```bash
cd ~/Swarm-Prediction && ./Prediction/BotDeal/sync_worktree.sh
```

## Quality gate

```bash
uv run --extra forecast pytest tests/test_br_hardware.py tests/test_mcp_server.py -q
```
