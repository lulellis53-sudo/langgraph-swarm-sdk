# RAG techniques for Swarm — design

Date: 2026-10-02 · Source: `~/Documentos/RAGTECHNIQUES.MD` · Status: awaiting review

## Goal

Apply the techniques from the RAG manual that improve Swarm's retrieval quality or
prompt token cost on the 16 GB Intel host, and keep a technique only if a measured
retrieval metric improves.

Constraints (from the request and `AGENTS.md`): offline deterministic tests, no new
network calls, no new dependencies, quality gate stays green, each technique behind a
config flag that defaults to the current behavior.

Success: a recorded before/after table of recall@k and MRR for each technique on the
labeled fixture, plus the gate green.

## Existing baseline (not re-implemented)

| Capability | Where |
|---|---|
| Dense + BM25 hybrid with RRF fusion | `retrieval/hybrid.py` |
| Near-duplicate removal, keyword and FastEmbed cross-encoder rerank | `retrieval/recall.py`, `retrieval/rerank.py` |
| Semantic cache | `retrieval/cache.py` |
| Header-aware Markdown chunking | `retrieval/rag_ingest.py:chunk_markdown` |
| Recall entry point used by the swarm | `core/swarm.py:recall` → `recall_hits` |

## Out of scope

Query transformation and Contextual Retrieval (an LLM call per query or chunk, which
costs the tokens this project is cutting), GraphRAG, ColPali, LLMLingua, Redis and
RabbitMQ ingestion, the C/C++ and Rust sections, LLM-judge metrics (Ragas, TruLens).

## Components

### 1. Retrieval metrics (`Agents/benchmark/Tasks/rag_quality/`)

- Fixture `fixtures/corpus.jsonl` (24 passages) and `fixtures/queries.jsonl` (12 queries:
  10 with a set of relevant passage ids, 2 unanswerable). Deterministic, written by hand,
  no network.
- `metrics.py`: pure functions `recall_at_k(ranked, relevant, k)` and
  `mrr(ranked, relevant)`.
- `benchmark_rag_quality.py`: builds a `SqliteVecStore` with a deterministic
  `BagOfWordsEmbedder`, runs `recall_hits` per query, prints a table, optional `--json`.
  It reports recall@k, MRR and the false-injection rate (share of unanswerable queries
  that still return passages). Follows the layout of the
  existing `Tasks/` benchmarks (`task.yaml`, a test).
- Limitation, stated in the output: `BagOfWordsEmbedder` is lexical, so the dense signal
  is weak. (`HashEmbedder` is not usable here: it returns a random vector per exact text.) The benchmark measures ordering and gating logic, not embedding quality.
  When `llama-server` or FastEmbed is available the same benchmark accepts
  `--embedder`.

### 2. U-shaped ordering (`retrieval/ordering.py`)

Pure function `u_shape(items: Sequence[T]) -> list[T]` taking items best-first and
returning the manual's §8.3 layout: rank 1 first, rank 2 last, the weakest in the middle.
Applied where recalled snippets become prompt text (`core/swarm.py`, the memories
block), behind `rag.u_shape_order` (default `false`).

Invariant: output is a permutation of the input; length 0, 1 and 2 are unchanged.

### 3. Parent-child chunking (`retrieval/rag_ingest.py`)

`chunk_markdown` already yields section-level chunks with a header context. Add an
optional `child_size` that splits each chunk into smaller children for embedding, each
carrying `parent_id`. Search runs over children; `RetrievalResult` returns the parent
text deduplicated by `parent_id`, keeping the best child score.

Behind `rag.parent_child` and `rag.child_size` (default `false` / 400). With it off, behavior and chunk ids are
unchanged.

### 4. Scored reranking and CRAG-lite gate

- `Reranker` gains an optional `rerank_scored(query, documents) -> list[tuple[str, float]]`.
  The existing `rerank` stays, so current callers and the Protocol do not break.
  `FastEmbedReranker` returns cross-encoder scores; `KeywordReranker` returns the
  normalized token-overlap score.
- `retrieval/gate.py`: `classify(scores, high, low) -> Confidence` with three states
  `HIGH`, `AMBIGUOUS`, `LOW`, from the best score against two configured thresholds.
- `recall_hits` is unchanged. A new `recall_with_confidence(..., gate)` returns a
  `RecallResult(hits, confidence)`. `LOW` returns no hits, so the caller does not inject
  weak memories. `AMBIGUOUS` returns the hits with the confidence attached. Fallback to WebSearch is a decision for the caller and is not wired by
  this spec.
- Thresholds are in the active reranker's score scale (`KeywordReranker` is in [0, 1];
  `FastEmbedReranker` returns raw logits), so they are calibrated per reranker from the
  benchmark in component 1 and stored in `rag.gate`. Default: gate off.

## Data flow

query → hybrid search (existing) → dedupe (existing) → scored rerank → gate →
optional U-shape → prompt. Parent-child sits on the ingestion path in front of the
index and does not change this flow.

## Error handling

- Gate and ordering never raise on empty input; they return empty.
- A missing score (a reranker without `rerank_scored`) disables the gate for that call
  and logs once at debug level; it does not fail the recall.
- `child_size` below 1 raises `ValueError` at construction; a child size at or above the
  chunk size yields one child per parent.

## Testing

- Unit: `recall_at_k`, `mrr`, `u_shape` (permutation property, small sizes), `classify`
  at the threshold boundaries, parent dedupe keeps the best child.
- Integration: each flag off reproduces the current `recall_hits` output exactly; each
  flag on is exercised through `recall_hits` or `RAGIngestionPipeline`.
- Benchmark: `rag_quality` runs with baseline and with each technique enabled; the
  table goes in this spec's results section.

## Acceptance rule

A retrieval technique's flag may default to `true` only if it improves recall@k or MRR on
the fixture without lowering the other. The gate is judged on the false-injection rate
(it must reach 0 on the unanswerable queries) without lowering recall@k or MRR. Otherwise it ships off or is reverted, and the
result is recorded here. U-shape ordering changes prompt order, not retrieval, so it is
judged on a prompt-assembly test instead of the retrieval metrics.

## Results

Measured with `cd Agents && uv run python -m benchmark.Tasks.rag_quality.benchmark_rag_quality`
(k=3, `BagOfWordsEmbedder`, `KeywordReranker`, 10 answerable and 2 unanswerable queries).

| variant | recall@3 | MRR | false_inject_rate |
|---|---|---|---|
| baseline | 0.667 | 0.950 | 1.000 |
| gate (`low=0.27`, `high=0.5`) | 0.667 | 0.950 | 0.000 |
| pipeline_flat (`RAGIngestionPipeline`, dense only) | 0.583 | 0.925 | 1.000 |
| pipeline_parent_child (`child_size=40`) | 0.583 | 0.950 | 1.000 |

Gate calibration: best `KeywordReranker` score per query ranged from 0.286 to 0.857 for the
10 answerable queries and 0.00 to 0.25 for the 2 unanswerable ones. A 0.05 grid has no
value that separates them (0.25 still injects, 0.30 drops an answerable query), so `low` is
0.27, the midpoint of the gap (0.25, 0.286]. The margin is about 0.016 on a 12-query
fixture; treat the thresholds as a starting point to recalibrate on real queries.

Decisions (acceptance rule applied):

- **Scored rerank + gate: implemented, default off.** On the fixture it reaches
  false-injection 0.000 with recall@3 and MRR unchanged, so it meets the rule. It ships off
  because the margin is 0.016 on 12 queries and the thresholds are only valid for
  `KeywordReranker`; the production reranker (`FastEmbedReranker`) scores in logits.
  Enable per deployment after recalibrating `rag.gate.low/high`.
- **Parent-child chunking: implemented, default off.** MRR 0.950 against 0.925 with equal
  recall@3 technically meets the rule, but the gain is one query moving one rank, which is
  within noise on 10 answerable queries. It also changes what `swarm ingest` persists
  (children plus `parents.json`), so it stays opt-in.
- **U-shaped ordering: implemented, default off.** It changes prompt order, not retrieval,
  so the retrieval metrics do not apply; covered by `tests/test_rag_ordering.py`.
