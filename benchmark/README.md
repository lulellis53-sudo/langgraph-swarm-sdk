# Benchmarks

Task folders under `Tasks/{name}/` measure token usage, cache hits, retrieval quality, and swarm behavior using **predefined models** from [config/swarm.yaml](../config/swarm.yaml) and scripted chat models (no API keys in CI).

## Token-minimization pipeline (what we score)

1. Exact + semantic cache before any LLM call.
2. Router on `think_level: low` and cheapest route in `model_select.routes`.
3. Hybrid dense + BM25 recall, dedupe, rerank, inject only top-k snippets.
4. Tokenizer budget + think-level caps before prompts.
5. Parallel fan-out with JSON briefs instead of full transcripts.

## Run

```bash
uv run pytest benchmark/ -q
uv run python -m benchmark.run --task token_cache_hit
```

Results (optional): `benchmark/results/{task}/` (gitignored).
