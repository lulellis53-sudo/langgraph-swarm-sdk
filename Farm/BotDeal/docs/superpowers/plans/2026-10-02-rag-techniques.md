# RAG Techniques Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add retrieval metrics, U-shaped prompt ordering, parent-child chunking and a scored CRAG-lite confidence gate to Swarm, each behind a default-off flag and kept on only if a measured metric improves.

**Architecture:** A deterministic `rag_quality` benchmark (recall@k, MRR, false-injection rate) is built first and gives the baseline. The three techniques are small additive units (`retrieval/ordering.py`, `retrieval/gate.py`, an optional child index in `RAGIngestionPipeline`) wired through one new `rag:` config block. `recall_hits` is left untouched; the gate uses a new sibling function.

**Tech Stack:** Python >=3.14.5, pydantic v2, numpy, pytest, `uv run`, ruff (line length 100). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-02-rag-techniques-design.md`

## Global Constraints

- Offline deterministic tests, no network, no API keys.
- No new dependencies; add nothing to `pyproject.toml`.
- Every new flag defaults to `false`; with all flags off, `recall_hits`, `SwarmSDK._recall` and `RAGIngestionPipeline` behave exactly as before.
- New modules start with a docstring, then `from __future__ import annotations` (repo rule in `AGENTS.md`).
- Ruff `line-length = 100`; no new `# noqa`, `# type: ignore`, skip or xfail.
- Run commands from `/Users/usuario/Swarm` with `uv run --extra dev ...`. Test paths: `Agents/benchmark` and `tests` (both are in `testpaths`).
- Quality gate before "done": `uv run --extra dev pytest -q`, `uv run --extra dev ruff check src Agents/benchmark Main`, `uv run --extra dev ruff format --check src Agents/benchmark Main`, `uv run python -m compileall -q src Agents Main`, `uv run python -m swarm_sdk.agents.validate`. `ty` is not installed; do not claim it ran.
- Commit only if the user asks, and never create branches (`AGENTS.md`). The "Commit" steps below are therefore **skipped unless the user requests commits**; list the changed files in the report instead.

## Review Focus

Inputs and conditions the spec implies but no feature test would otherwise exercise, most likely first:

1. Empty recall result (no hits) through the gate and through `u_shape`: must return empty, not raise.
2. A reranker without `rerank_scored` (for example `IdentityReranker`) with the gate enabled: must behave as gate-off, not fail.
3. `FastEmbedReranker` scores are unbounded logits while `KeywordReranker` scores are in `[0, 1]`: thresholds are per reranker. The config comment and the spec must say so.
4. Re-ingesting text twice with the same `source_file` in parent-child mode: parent ids must not collide.
5. `save` then `load` of a parent-child pipeline: queries must return the same parents.
6. Non-ASCII text (for example `café`, CJK) through `split_children` and `u_shape`: no crash, text preserved.

---

### Task 1: Retrieval metrics

**Files:**
- Create: `Agents/benchmark/Tasks/rag_quality/metrics.py`
- Test: `Agents/benchmark/Tasks/rag_quality/test_metrics.py`

**Interfaces:**
- Produces: `recall_at_k(ranked: Sequence[str], relevant: Collection[str], k: int) -> float`, `mrr(ranked: Sequence[str], relevant: Collection[str]) -> float`.

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for the retrieval metrics."""

from __future__ import annotations

import pytest

from benchmark.Tasks.rag_quality.metrics import mrr, recall_at_k


def test_recall_at_k_counts_relevant_in_top_k() -> None:
    assert recall_at_k(["a", "b", "c"], {"a", "c"}, 2) == pytest.approx(0.5)
    assert recall_at_k(["a", "b", "c"], {"a", "c"}, 3) == pytest.approx(1.0)


def test_recall_at_k_edge_cases() -> None:
    assert recall_at_k([], {"a"}, 3) == 0.0
    assert recall_at_k(["a"], set(), 3) == 0.0  # no relevant ids: undefined, reported as 0
    with pytest.raises(ValueError):
        recall_at_k(["a"], {"a"}, 0)


def test_mrr_is_reciprocal_rank_of_first_relevant() -> None:
    assert mrr(["x", "a", "b"], {"a", "b"}) == pytest.approx(0.5)
    assert mrr(["a"], {"a"}) == 1.0
    assert mrr(["x", "y"], {"a"}) == 0.0
    assert mrr([], {"a"}) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest Agents/benchmark/Tasks/rag_quality/test_metrics.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'benchmark.Tasks.rag_quality.metrics'`.

- [ ] **Step 3: Write minimal implementation**

```python
"""Retrieval metrics over ranked passage ids."""

from __future__ import annotations

from collections.abc import Collection, Sequence


def recall_at_k(ranked: Sequence[str], relevant: Collection[str], k: int) -> float:
    """Return the fraction of ``relevant`` ids found in the first ``k`` ranked ids.

    An empty ``relevant`` set returns 0.0 (the metric is undefined there).

    Raises:
        ValueError: If ``k`` is below 1.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    if not relevant:
        return 0.0
    found = len(set(ranked[:k]) & set(relevant))
    return found / len(set(relevant))


def mrr(ranked: Sequence[str], relevant: Collection[str]) -> float:
    """Return the reciprocal rank of the first relevant id, or 0.0 when absent."""
    wanted = set(relevant)
    for position, item in enumerate(ranked, start=1):
        if item in wanted:
            return 1.0 / position
    return 0.0


__all__ = ["mrr", "recall_at_k"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest Agents/benchmark/Tasks/rag_quality/test_metrics.py -q`
Expected: 3 passed.

- [ ] **Step 5: Lint and format**

Run: `uv run --extra dev ruff format Agents/benchmark/Tasks/rag_quality && uv run --extra dev ruff check Agents/benchmark/Tasks/rag_quality`
Expected: `All checks passed!`

---

### Task 2: Fixture and baseline benchmark

**Files:**
- Create: `Agents/benchmark/Tasks/rag_quality/fixtures/corpus.jsonl`
- Create: `Agents/benchmark/Tasks/rag_quality/fixtures/queries.jsonl`
- Create: `Agents/benchmark/Tasks/rag_quality/embedders.py`
- Create: `Agents/benchmark/Tasks/rag_quality/benchmark_rag_quality.py`
- Create: `Agents/benchmark/Tasks/rag_quality/task.yaml`
- Test: `Agents/benchmark/Tasks/rag_quality/test_rag_quality.py`
- Modify: `docs/superpowers/specs/2026-10-02-rag-techniques-design.md` (Results section, baseline row)

**Interfaces:**
- Consumes: `recall_at_k`, `mrr` from Task 1; `recall_hits(query, store, embedder, reranker, *, retrieve_k, rerank_k, dedup_threshold, hybrid, hybrid_enabled) -> list[MemoryHit]`; `SqliteVecStore(path: str, dim: int)` with `.add(text, vector)` and `.close()`; `KeywordReranker`; `HybridSearchConfig`.
- Produces: `BagOfWordsEmbedder(dim: int = 256)` with `.dim` and `.embed(texts: list[str], *, query: bool = False) -> np.ndarray` (float32, L2-normalized rows); `Passage(id: str, text: str)`, `Query(q: str, relevant: tuple[str, ...])` frozen dataclasses; `Ranker = Callable[[str], list[str]]`; `load_fixture() -> tuple[list[Passage], list[Query]]`; `evaluate(rank: Ranker, queries: Sequence[Query], k: int = 3) -> dict[str, float]` returning keys `recall_at_k`, `mrr`, `false_inject_rate`; `recall_ranker(passages) -> ContextManager[Ranker]`; `run(*, k: int = 3) -> dict[str, Any]`.

- [ ] **Step 1: Create the fixtures**

`fixtures/corpus.jsonl` (24 lines; write exactly):

```jsonl
{"id": "p01", "text": "The episodic memory store keeps int8 quantized vectors in a sqlite-vec table."}
{"id": "p02", "text": "Memory rows are written with their text and an embedding vector so recall can search by similarity."}
{"id": "p03", "text": "sqlite-vec also provides an FTS5 keyword index that runs next to the vector table."}
{"id": "p04", "text": "Hybrid search fuses dense similarity ranking with BM25 keyword ranking."}
{"id": "p05", "text": "Reciprocal rank fusion adds one over k plus rank for each ranking source."}
{"id": "p06", "text": "The fusion constant k defaults to sixty and each source has its own weight."}
{"id": "p07", "text": "The semantic cache returns a stored answer when a new prompt is nearly identical to an earlier one."}
{"id": "p08", "text": "Cache entries expire after a configurable number of days to avoid stale answers."}
{"id": "p09", "text": "Empty answers are never cached because they would poison future lookups."}
{"id": "p10", "text": "The token budget packs the system prompt, recalled memories and turns under a hard limit."}
{"id": "p11", "text": "Think level low medium or high selects how many tokens a request may use."}
{"id": "p12", "text": "When the prompt is too long the oldest turns are dropped before memories."}
{"id": "p13", "text": "The circuit breaker opens a provider after repeated failures."}
{"id": "p14", "text": "A half open breaker allows one probe call before closing again."}
{"id": "p15", "text": "Fallback models take over while the primary provider breaker is open."}
{"id": "p16", "text": "Checkpoints persist graph state so a swarm run can resume after a crash."}
{"id": "p17", "text": "The checkpoint saver writes to SQLite in write ahead log mode."}
{"id": "p18", "text": "Each conversation thread has its own thread id and checkpoint history."}
{"id": "p19", "text": "OpenCL kernels compute batch cosine similarity on the Radeon GPU."}
{"id": "p20", "text": "Without a GPU the same math falls back to NumPy on the CPU."}
{"id": "p21", "text": "The GPU vector store does brute force top k search and not an approximate index."}
{"id": "p22", "text": "API keys are stored in the macOS Keychain and never in YAML files."}
{"id": "p23", "text": "The vault command sets and reads secrets by name."}
{"id": "p24", "text": "Configuration files only hold environment variable names for credentials."}
```

`fixtures/queries.jsonl` (12 lines; the last two have no relevant passage):

```jsonl
{"q": "how are int8 vectors stored in sqlite", "relevant": ["p01", "p02"]}
{"q": "rank fusion of keyword and dense results", "relevant": ["p04", "p05", "p06"]}
{"q": "when does the cache return a stored answer", "relevant": ["p07", "p08"]}
{"q": "limit on prompt tokens for a request", "relevant": ["p10", "p11", "p12"]}
{"q": "what happens when a provider keeps failing", "relevant": ["p13", "p14", "p15"]}
{"q": "resume a run after crash", "relevant": ["p16", "p17"]}
{"q": "gpu cosine similarity on radeon", "relevant": ["p19", "p20", "p21"]}
{"q": "where are api keys kept", "relevant": ["p22", "p23", "p24"]}
{"q": "thread id history", "relevant": ["p18"]}
{"q": "keyword index next to the vector table", "relevant": ["p03"]}
{"q": "recipe for pasta carbonara", "relevant": []}
{"q": "football world cup results", "relevant": []}
```

- [ ] **Step 1b: Write the embedder**

`HashEmbedder` produces a seeded *random* vector per exact text, so its similarity is noise
and cannot be used to measure retrieval. The benchmark and the parent-child tests use this
deterministic lexical embedder instead (hashing trick; `blake2b` because Python's `hash` is
salted per process).

`embedders.py`:

```python
"""Deterministic bag-of-words embedder for offline retrieval tests."""

from __future__ import annotations

import hashlib
import re

import numpy as np

_WORD = re.compile(r"\w+")


class BagOfWordsEmbedder:
    """Hash each lowercase word into one of ``dim`` buckets and L2-normalize the counts."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        del query
        rows = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in _WORD.findall(text.lower()):
                digest = hashlib.blake2b(word.encode(), digest_size=4).digest()
                rows[row, int.from_bytes(digest, "little") % self.dim] += 1.0
        norms = np.linalg.norm(rows, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return rows / norms


__all__ = ["BagOfWordsEmbedder"]
```

- [ ] **Step 2: Write the failing test**

```python
"""CI check for the rag_quality benchmark: fixture integrity and baseline report shape."""

from __future__ import annotations

import pytest
from benchmark.Tasks.rag_quality.benchmark_rag_quality import evaluate, load_fixture, run
from benchmark.Tasks.rag_quality.embedders import BagOfWordsEmbedder


def test_bag_of_words_embedder_is_deterministic_and_lexical() -> None:
    embedder = BagOfWordsEmbedder()
    a, b, c = embedder.embed(["sqlite vector memory", "sqlite vector memory", "pasta recipe"])
    assert (a == b).all()
    assert float(a @ a) == pytest.approx(1.0)
    related = embedder.embed(["vector memory store"])[0]
    assert float(a @ related) > float(a @ c)
    assert embedder.embed([""])[0].sum() == 0.0  # empty text stays the zero vector


def test_fixture_is_consistent() -> None:
    passages, queries = load_fixture()
    ids = {p.id for p in passages}
    assert len(ids) == len(passages) == 24
    assert len(queries) == 12
    assert all(set(q.relevant) <= ids for q in queries)
    assert sum(1 for q in queries if not q.relevant) == 2


def test_evaluate_scores_a_perfect_and_an_empty_ranker() -> None:
    _, queries = load_fixture()
    relevant = {q.q: list(q.relevant) for q in queries}
    perfect = evaluate(lambda q: relevant[q], queries, k=3)
    assert perfect["mrr"] == 1.0
    assert perfect["false_inject_rate"] == 0.0
    empty = evaluate(lambda q: [], queries, k=3)
    assert empty == {"recall_at_k": 0.0, "mrr": 0.0, "false_inject_rate": 0.0}


def test_baseline_run_reports_bounded_metrics() -> None:
    report = run()
    row = report["variants"]["baseline"]
    assert set(row) == {"recall_at_k", "mrr", "false_inject_rate"}
    assert all(0.0 <= value <= 1.0 for value in row.values())
    assert row["recall_at_k"] > 0.0  # the fixture is retrievable at all
    assert row["false_inject_rate"] == 1.0  # ungated recall always injects something
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --extra dev pytest Agents/benchmark/Tasks/rag_quality/test_rag_quality.py -q`
Expected: FAIL, `ModuleNotFoundError: ... benchmark_rag_quality` (or `embedders`).

- [ ] **Step 4: Write the implementation**

`benchmark_rag_quality.py`:

```python
"""Offline retrieval-quality benchmark: recall@k, MRR and false-injection rate.

The dense signal comes from ``BagOfWordsEmbedder`` (lexical, not semantic), so
this measures ordering and gating logic rather than embedding quality. Pass a
different embedder to ``recall_ranker`` to measure a real model.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmark.Tasks.rag_quality.metrics import mrr, recall_at_k
from benchmark.Tasks.rag_quality.embedders import BagOfWordsEmbedder
from swarm_sdk.memory.sqlite_vec import SqliteVecStore
from swarm_sdk.retrieval.embeddings import Embedder
from swarm_sdk.retrieval.hybrid import HybridSearchConfig
from swarm_sdk.retrieval.recall import recall_hits
from swarm_sdk.retrieval.rerank import KeywordReranker

FIXTURES = Path(__file__).parent / "fixtures"
DIM = 256
RETRIEVE_K = 8
RERANK_K = 4

type Ranker = Callable[[str], list[str]]


@dataclass(frozen=True, slots=True)
class Passage:
    id: str
    text: str


@dataclass(frozen=True, slots=True)
class Query:
    q: str
    relevant: tuple[str, ...]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def load_fixture() -> tuple[list[Passage], list[Query]]:
    """Load the labeled corpus and queries."""
    passages = [Passage(r["id"], r["text"]) for r in _read_jsonl(FIXTURES / "corpus.jsonl")]
    queries = [Query(r["q"], tuple(r["relevant"])) for r in _read_jsonl(FIXTURES / "queries.jsonl")]
    return passages, queries


def evaluate(rank: Ranker, queries: Sequence[Query], k: int = 3) -> dict[str, float]:
    """Return mean recall@k and MRR over answerable queries and the false-injection rate.

    ``false_inject_rate`` is the share of unanswerable queries (no relevant
    passage) for which the ranker still returned something.
    """
    answerable = [q for q in queries if q.relevant]
    unanswerable = [q for q in queries if not q.relevant]
    recalls, rrs = [], []
    for query in answerable:
        ranked = rank(query.q)
        recalls.append(recall_at_k(ranked, query.relevant, k))
        rrs.append(mrr(ranked, query.relevant))
    injected = sum(1 for q in unanswerable if rank(q.q))
    return {
        "recall_at_k": sum(recalls) / len(recalls) if recalls else 0.0,
        "mrr": sum(rrs) / len(rrs) if rrs else 0.0,
        "false_inject_rate": injected / len(unanswerable) if unanswerable else 0.0,
    }


@contextmanager
def recall_ranker(
    passages: Sequence[Passage], embedder: Embedder | None = None
) -> Iterator[Ranker]:
    """Yield a ranker backed by a temporary ``SqliteVecStore`` and ``recall_hits``."""
    embedder = embedder or BagOfWordsEmbedder(DIM)
    id_by_text = {p.text: p.id for p in passages}
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteVecStore(str(Path(tmp) / "m.db"), dim=embedder.dim)
        for passage in passages:
            store.add(passage.text, embedder.embed([passage.text], query=False)[0])
        reranker = KeywordReranker()
        hybrid = HybridSearchConfig()

        def rank(query: str) -> list[str]:
            hits = recall_hits(
                query,
                store,
                embedder,
                reranker,
                retrieve_k=RETRIEVE_K,
                rerank_k=RERANK_K,
                dedup_threshold=0.99,
                hybrid=hybrid,
                hybrid_enabled=True,
            )
            return [id_by_text[hit.text] for hit in hits]

        try:
            yield rank
        finally:
            store.close()


def run(*, k: int = 3) -> dict[str, Any]:
    """Run every variant and return the metric table."""
    passages, queries = load_fixture()
    variants: dict[str, dict[str, float]] = {}
    with recall_ranker(passages) as baseline:
        variants["baseline"] = evaluate(baseline, queries, k)
    return {"k": k, "n_passages": len(passages), "n_queries": len(queries), "variants": variants}


def format_table(report: dict[str, Any]) -> str:
    lines = [f"{'variant':<22}{'recall@k':>10}{'mrr':>8}{'false_inject':>14}"]
    for name, row in report["variants"].items():
        lines.append(
            f"{name:<22}{row['recall_at_k']:>10.3f}{row['mrr']:>8.3f}{row['false_inject_rate']:>14.3f}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--json", type=Path, help="also write the report here")
    args = parser.parse_args()
    report = run(k=args.k)
    print(format_table(report))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`task.yaml`:

```yaml
name: rag_quality
sdk_entry: benchmark.Tasks.rag_quality.benchmark_rag_quality.run
metrics:
  - recall_at_k
  - mrr
  - false_inject_rate
models: none (offline, BagOfWordsEmbedder, KeywordReranker)
pass:
  baseline_recall_at_k_gt: 0.0
```

- [ ] **Step 5: Run tests, lint, format**

Run: `uv run --extra dev ruff format Agents/benchmark/Tasks/rag_quality && uv run --extra dev ruff check Agents/benchmark/Tasks/rag_quality && uv run --extra dev pytest Agents/benchmark/Tasks/rag_quality -q`
Expected: ruff clean; 7 passed (3 metrics, 4 benchmark).
If `false_inject_rate == 1.0` fails because `recall_hits` returns nothing for an unanswerable query, that is real information: record it in the spec instead of editing the assertion, and change the assertion to the measured value with a comment explaining why.

- [ ] **Step 6: Record the baseline**

Run: `cd Agents && uv run python -m benchmark.Tasks.rag_quality.benchmark_rag_quality`
Copy the printed `baseline` row into the spec's `## Results` section as a table with columns `variant | recall@3 | MRR | false_inject_rate`.

---

### Task 3: U-shaped ordering and the `rag:` config block

**Files:**
- Create: `src/swarm_sdk/retrieval/ordering.py`
- Modify: `src/swarm_sdk/config/loader.py` (add `RagConfig`, field on `SwarmFileConfig`, builder argument)
- Modify: `src/swarm_sdk/core/swarm.py:382-383` (`_recall`)
- Modify: `src/swarm_sdk/agents/config/swarm.yaml` (document the block)
- Test: `tests/test_rag_ordering.py`

**Interfaces:**
- Produces: `u_shape[T](items: Sequence[T]) -> list[T]` (input best-first); `order_for_prompt[T](items: Sequence[T], *, enabled: bool) -> list[T]`; `RagConfig(u_shape_order: bool = False, parent_child: bool = False, child_size: int = 400, gate: GateConfig)` in `swarm_sdk.config.loader`. `GateConfig` is created in Task 4, so in this task `RagConfig` has only `u_shape_order`, `parent_child` and `child_size`; Task 4 adds `gate`.
- Consumes: `sdk_with_router(tmp_path, raw)` from `Agents/benchmark/tests/fakes.py` (builds a `SwarmSDK` with `HashEmbedder(32)`, `IdentityReranker`, `OpenClVecStore(32)`).

- [ ] **Step 1: Write the failing tests**

`tests/test_rag_ordering.py`:

```python
"""U-shaped passage ordering and its wiring into SwarmSDK._recall."""

from __future__ import annotations

from pathlib import Path

from benchmark.tests.fakes import sdk_with_router
from swarm_sdk.config.loader import RagConfig
from swarm_sdk.retrieval.ordering import order_for_prompt, u_shape


def test_u_shape_puts_best_first_and_second_best_last() -> None:
    assert u_shape(["r1", "r2", "r3", "r4", "r5"]) == ["r1", "r3", "r5", "r4", "r2"]
    assert u_shape(["r1", "r2", "r3", "r4"]) == ["r1", "r3", "r4", "r2"]


def test_u_shape_small_and_non_ascii_inputs() -> None:
    assert u_shape([]) == []
    assert u_shape(["a"]) == ["a"]
    assert u_shape(["a", "b"]) == ["a", "b"]
    assert sorted(u_shape(["café", "東京", "ß"])) == sorted(["café", "東京", "ß"])


def test_order_for_prompt_is_identity_when_disabled() -> None:
    items = ["a", "b", "c", "d"]
    assert order_for_prompt(items, enabled=False) == items
    assert order_for_prompt(items, enabled=True) == u_shape(items)


def test_rag_config_defaults_are_off() -> None:
    cfg = RagConfig()
    assert cfg.u_shape_order is False
    assert cfg.parent_child is False
    assert cfg.child_size == 400


def test_sdk_recall_honors_the_flag(tmp_path: Path) -> None:
    sdk = sdk_with_router(tmp_path, "{}")
    for text in ["alpha cache", "beta cache", "gamma cache", "delta cache"]:
        sdk.memory.add(text, sdk.embedder.embed([text], query=False)[0])
    off = sdk._recall("cache")
    assert len(off) >= 3
    sdk.file_config.rag.u_shape_order = True
    on = sdk._recall("cache")
    assert on == u_shape(off)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest tests/test_rag_ordering.py -q`
Expected: FAIL, `ModuleNotFoundError: swarm_sdk.retrieval.ordering` (or `ImportError: RagConfig`).

- [ ] **Step 3: Implement `ordering.py`**

```python
"""Lost-in-the-middle mitigation: place the strongest passages at both ends of a prompt."""

from __future__ import annotations

from collections.abc import Sequence


def u_shape[T](items: Sequence[T]) -> list[T]:
    """Reorder best-first ``items`` so rank 1 is first and rank 2 is last.

    Ranks alternate between the front and the back, which leaves the weakest
    items in the middle, where decoder-only models attend least. The result is
    always a permutation of the input.
    """
    front: list[T] = []
    back: list[T] = []
    for index, item in enumerate(items):
        (front if index % 2 == 0 else back).append(item)
    return front + back[::-1]


def order_for_prompt[T](items: Sequence[T], *, enabled: bool) -> list[T]:
    """Return ``items`` unchanged, or U-shaped when ``enabled``."""
    return u_shape(items) if enabled else list(items)


__all__ = ["order_for_prompt", "u_shape"]
```

- [ ] **Step 4: Add `RagConfig` to `config/loader.py`**

After `RerankConfig` (line ~110) add:

```python
class RagConfig(BaseModel):
    """Opt-in RAG techniques; every flag defaults to the previous behavior."""

    u_shape_order: bool = False
    parent_child: bool = False
    child_size: int = Field(default=400, ge=1)
```

Add to `SwarmFileConfig` after the `rerank` field: `rag: RagConfig = Field(default_factory=RagConfig)`.
In the `SwarmFileConfig(...)` construction (after `rerank=RerankConfig.model_validate(...)`) add: `rag=RagConfig.model_validate(data.get("rag", {})),`.

- [ ] **Step 5: Wire `_recall`**

In `src/swarm_sdk/core/swarm.py` add the import `from swarm_sdk.retrieval.ordering import order_for_prompt` (alphabetical among the `swarm_sdk.retrieval` imports) and replace:

```python
    def _recall(self, text: str) -> list[str]:
        return [hit.text for hit in self.recall(text)]
```

with:

```python
    def _recall(self, text: str) -> list[str]:
        texts = [hit.text for hit in self.recall(text)]
        return order_for_prompt(texts, enabled=self.file_config.rag.u_shape_order)
```

- [ ] **Step 6: Document in `src/swarm_sdk/agents/config/swarm.yaml`**

Append:

```yaml
rag:                            # opt-in techniques; all default to off
  u_shape_order: false          # put the best recalled memories first and last in the prompt
  parent_child: false           # RAGIngestionPipeline: index small children, return the parent
  child_size: 400               # characters per child chunk when parent_child is true
```

- [ ] **Step 7: Run tests, lint, format**

Run: `uv run --extra dev ruff format src/swarm_sdk/retrieval/ordering.py src/swarm_sdk/config/loader.py src/swarm_sdk/core/swarm.py tests/test_rag_ordering.py && uv run --extra dev ruff check src tests/test_rag_ordering.py && uv run --extra dev pytest tests/test_rag_ordering.py Agents/benchmark/tests/test_config.py -q`
Expected: clean; all pass.

---

### Task 4: Scored reranking and the CRAG-lite gate

**Files:**
- Create: `src/swarm_sdk/retrieval/gate.py`
- Modify: `src/swarm_sdk/retrieval/rerank.py` (add `rerank_scored` to `KeywordReranker`, `FastEmbedReranker`; add `ScoredReranker` Protocol)
- Modify: `src/swarm_sdk/retrieval/recall.py` (add `RecallResult`, `recall_with_confidence`, shared helper)
- Modify: `src/swarm_sdk/config/loader.py` (`GateConfig` import, `RagConfig.gate`)
- Modify: `src/swarm_sdk/core/swarm.py:369-380` (`recall` uses the gate when enabled)
- Modify: `src/swarm_sdk/retrieval/__init__.py` (export new names)
- Modify: `Agents/benchmark/Tasks/rag_quality/benchmark_rag_quality.py` (add `gate` variant)
- Test: `tests/test_rag_gate.py`, extend `Agents/benchmark/Tasks/rag_quality/test_rag_quality.py`

**Interfaces:**
- Produces:
  - `Confidence` (`enum.StrEnum`: `HIGH`, `AMBIGUOUS`, `LOW`); `GateConfig(enabled: bool = False, high: float = 0.5, low: float = 0.2)` (validates `low <= high`); `classify(scores: Sequence[float], config: GateConfig) -> Confidence` (empty scores return `LOW`; best score `>= high` is `HIGH`; `< low` is `LOW`; otherwise `AMBIGUOUS`).
  - `ScoredReranker` Protocol: `rerank_scored(self, query: str, documents: list[str]) -> list[tuple[str, float]]` (best first).
  - `RecallResult(hits: list[MemoryHit], confidence: Confidence | None)` frozen dataclass; `recall_with_confidence(query, store, embedder, reranker, *, retrieve_k, rerank_k, dedup_threshold, hybrid=None, hybrid_enabled=True, gate: GateConfig) -> RecallResult`. `LOW` returns `hits=[]`. A reranker without `rerank_scored` returns the normal hits with `confidence=None`.
- Consumes: `RagConfig` from Task 3 (adds `gate: GateConfig = Field(default_factory=GateConfig)`).

- [ ] **Step 1: Write the failing tests**

`tests/test_rag_gate.py`:

```python
"""Scored reranking, the confidence gate and gated recall."""

from __future__ import annotations

from pathlib import Path

import pytest
from benchmark.tests.fakes import sdk_with_router

from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.retrieval.gate import Confidence, GateConfig, classify
from swarm_sdk.retrieval.rerank import IdentityReranker, KeywordReranker

CFG = GateConfig(enabled=True, high=0.5, low=0.2)


def test_classify_boundaries() -> None:
    assert classify([0.5, 0.1], CFG) is Confidence.HIGH
    assert classify([0.4999], CFG) is Confidence.AMBIGUOUS
    assert classify([0.2], CFG) is Confidence.AMBIGUOUS
    assert classify([0.1999], CFG) is Confidence.LOW
    assert classify([], CFG) is Confidence.LOW


def test_classify_uses_the_best_score_regardless_of_order() -> None:
    assert classify([0.0, 0.9, 0.1], CFG) is Confidence.HIGH


def test_gate_config_rejects_inverted_thresholds() -> None:
    with pytest.raises(ValueError):
        GateConfig(high=0.2, low=0.5)


def test_keyword_rerank_scored_matches_rerank_order_and_is_normalized() -> None:
    docs = ["alpha beta", "gamma", "alpha beta gamma delta"]
    scored = KeywordReranker().rerank_scored("alpha beta", docs)
    assert [d for d, _ in scored] == KeywordReranker().rerank("alpha beta", docs)
    assert all(0.0 <= s <= 1.0 for _, s in scored)
    assert scored[0][1] == 1.0
    assert KeywordReranker().rerank_scored("", docs)[0][1] == 0.0
    assert KeywordReranker().rerank_scored("x", []) == []


def _seed(sdk: SwarmSDK) -> None:
    for text in ["sqlite vector memory store", "semantic cache expiry", "token budget limit"]:
        sdk.memory.add(text, sdk.embedder.embed([text], query=False)[0])


def test_gate_drops_weak_recall_and_keeps_strong(tmp_path: Path) -> None:
    sdk = sdk_with_router(tmp_path, "{}")
    _seed(sdk)
    sdk.reranker = KeywordReranker()
    sdk.file_config.rag.gate = CFG
    assert sdk.recall("pasta carbonara") == []
    assert [h.text for h in sdk.recall("sqlite vector memory store")][0] == "sqlite vector memory store"


def test_gate_is_inert_without_a_scored_reranker(tmp_path: Path) -> None:
    sdk = sdk_with_router(tmp_path, "{}")
    _seed(sdk)
    sdk.reranker = IdentityReranker()
    off = sdk.recall("pasta carbonara")
    sdk.file_config.rag.gate = CFG
    assert sdk.recall("pasta carbonara") == off  # no scores, so no gating
    assert off != []


def test_gate_disabled_matches_recall_hits(tmp_path: Path) -> None:
    sdk = sdk_with_router(tmp_path, "{}")
    _seed(sdk)
    sdk.reranker = KeywordReranker()
    before = sdk.recall("sqlite")
    sdk.file_config.rag.gate = GateConfig(enabled=False)
    assert sdk.recall("sqlite") == before
```

Append to `Agents/benchmark/Tasks/rag_quality/test_rag_quality.py`:

```python
def test_gate_variant_removes_false_injection_without_losing_recall() -> None:
    report = run()
    base, gated = report["variants"]["baseline"], report["variants"]["gate"]
    assert gated["false_inject_rate"] == 0.0
    assert gated["recall_at_k"] >= base["recall_at_k"] - 1e-9
    assert gated["mrr"] >= base["mrr"] - 1e-9
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest tests/test_rag_gate.py -q`
Expected: FAIL, `ModuleNotFoundError: swarm_sdk.retrieval.gate`.

- [ ] **Step 3: Implement `gate.py`**

```python
"""CRAG-lite confidence gate over reranker scores (Yan et al., 2024)."""

from __future__ import annotations

import enum
from collections.abc import Sequence

from pydantic import BaseModel, model_validator


class Confidence(enum.StrEnum):
    HIGH = "high"
    AMBIGUOUS = "ambiguous"
    LOW = "low"


class GateConfig(BaseModel):
    """Thresholds are in the active reranker's score scale.

    ``KeywordReranker`` scores lie in [0, 1]; ``FastEmbedReranker`` returns raw
    cross-encoder logits, so calibrate ``high``/``low`` per reranker.
    """

    enabled: bool = False
    high: float = 0.5
    low: float = 0.2

    @model_validator(mode="after")
    def _ordered(self) -> GateConfig:
        if self.low > self.high:
            raise ValueError("gate.low must be <= gate.high")
        return self


def classify(scores: Sequence[float], config: GateConfig) -> Confidence:
    """Classify retrieval confidence from the best reranker score."""
    if not scores:
        return Confidence.LOW
    best = max(scores)
    if best >= config.high:
        return Confidence.HIGH
    if best < config.low:
        return Confidence.LOW
    return Confidence.AMBIGUOUS


__all__ = ["Confidence", "GateConfig", "classify"]
```

- [ ] **Step 4: Add scored reranking to `rerank.py`**

Add the Protocol after `Reranker`:

```python
class ScoredReranker(Protocol):
    def rerank_scored(self, query: str, documents: list[str]) -> list[tuple[str, float]]: ...
```

In `KeywordReranker` add (keep `rerank` unchanged):

```python
    def rerank_scored(self, query: str, documents: list[str]) -> list[tuple[str, float]]:
        """Return documents best-first with the fraction of query words each contains."""
        needles = set(query.lower().split())
        if not needles:
            return [(document, 0.0) for document in documents]

        def score(document: str) -> float:
            return len(needles & set(document.lower().split())) / len(needles)

        return sorted(((d, score(d)) for d in documents), key=lambda pair: pair[1], reverse=True)
```

In `FastEmbedReranker` add:

```python
    def rerank_scored(self, query: str, documents: list[str]) -> list[tuple[str, float]]:
        """Return documents best-first with raw cross-encoder scores (unbounded logits)."""
        if not documents:
            return []
        scores = [float(s) for s in self._load().rerank(query, documents)]
        order = sorted(range(len(documents)), key=lambda index: scores[index], reverse=True)
        return [(documents[index], scores[index]) for index in order]
```

Add `"ScoredReranker"` to `__all__`.

- [ ] **Step 5: Add `recall_with_confidence` to `recall.py`**

Add imports `from dataclasses import dataclass` and `from swarm_sdk.retrieval.gate import Confidence, GateConfig, classify`, and `from swarm_sdk.retrieval.rerank import Reranker, ScoredReranker`. Extract the shared candidate step out of `recall_hits` into a helper (behavior of `recall_hits` must not change):

```python
def _unique_candidates(
    query: str,
    store: MemoryStore,
    embedder: Embedder,
    *,
    retrieve_k: int,
    dedup_threshold: float,
    hybrid: HybridSearchConfig | None,
    hybrid_enabled: bool,
) -> tuple[list[str], dict[str, MemoryHit]]:
    """Return deduplicated candidate texts and a text-to-hit index."""
    hits = _candidate_hits(
        query,
        store,
        embedder,
        retrieve_k=retrieve_k,
        hybrid=hybrid,
        hybrid_enabled=hybrid_enabled,
    )
    if not hits:
        return [], {}
    texts = [hit.text for hit in hits]
    unique = dedupe_texts(texts, embedder.embed(texts, query=False), dedup_threshold)
    by_text: dict[str, MemoryHit] = {}
    for hit in hits:
        by_text.setdefault(hit.text, hit)
    return unique, by_text
```

`recall_hits` becomes: call `_unique_candidates(...)`; `if not unique: return []`; `ranked = reranker.rerank(query, unique)`; `return [by_text[text] for text in ranked[:rerank_k] if text in by_text]`.

Then add:

```python
@dataclass(frozen=True, slots=True)
class RecallResult:
    """Recalled hits plus the gate's verdict (``None`` when no scores were available)."""

    hits: list[MemoryHit]
    confidence: Confidence | None


def recall_with_confidence(
    query: str,
    store: MemoryStore,
    embedder: Embedder,
    reranker: Reranker,
    *,
    retrieve_k: int,
    rerank_k: int,
    dedup_threshold: float,
    gate: GateConfig,
    hybrid: HybridSearchConfig | None = None,
    hybrid_enabled: bool = True,
) -> RecallResult:
    """Like :func:`recall_hits`, but drop the hits when retrieval confidence is LOW.

    A reranker without ``rerank_scored`` cannot be gated: the plain reranked
    hits come back with ``confidence=None``.
    """
    unique, by_text = _unique_candidates(
        query,
        store,
        embedder,
        retrieve_k=retrieve_k,
        dedup_threshold=dedup_threshold,
        hybrid=hybrid,
        hybrid_enabled=hybrid_enabled,
    )
    if not unique:
        return RecallResult([], Confidence.LOW if gate.enabled else None)
    scored_fn = getattr(reranker, "rerank_scored", None)
    if not callable(scored_fn):
        ranked = reranker.rerank(query, unique)
        return RecallResult([by_text[t] for t in ranked[:rerank_k] if t in by_text], None)
    scored = cast(ScoredReranker, reranker).rerank_scored(query, unique)
    confidence = classify([score for _, score in scored], gate)
    if confidence is Confidence.LOW:
        return RecallResult([], confidence)
    hits = [by_text[text] for text, _ in scored[:rerank_k] if text in by_text]
    return RecallResult(hits, confidence)
```

Update `__all__` to `["RecallResult", "recall_hits", "recall_texts", "recall_with_confidence"]`.

- [ ] **Step 6: Add `gate` to `RagConfig` and use it in `SwarmSDK.recall`**

In `config/loader.py`: `from swarm_sdk.retrieval.gate import GateConfig` (next to the `HybridSearchConfig` import) and add to `RagConfig`: `gate: GateConfig = Field(default_factory=GateConfig)`.

In `core/swarm.py` replace `recall` with:

```python
    def recall(self, query: str, top_k: int | None = None) -> list[MemoryHit]:
        kwargs = {
            "retrieve_k": max(top_k or self.settings.rerank_k, self.settings.retrieve_k),
            "rerank_k": top_k or self.settings.rerank_k,
            "dedup_threshold": self.settings.dedup_threshold,
            "hybrid": self.file_config.hybrid_search,
            "hybrid_enabled": self.settings.hybrid_enabled,
        }
        gate = self.file_config.rag.gate
        if gate.enabled:
            return recall_with_confidence(
                query, self.memory, self.embedder, self.reranker, gate=gate, **kwargs
            ).hits
        return recall_hits(query, self.memory, self.embedder, self.reranker, **kwargs)
```

and import `recall_with_confidence` next to `recall_hits`. If a type checker complains about the `**kwargs` dict typing, build the two calls with explicit keyword arguments instead of a dict.

Document in `swarm.yaml` under `rag:` (comment the `gate:` keys: `enabled`, `high`, `low`, and the per-reranker scale note).

- [ ] **Step 7: Export from `retrieval/__init__.py`**

Add `Confidence`, `GateConfig`, `classify`, `RecallResult`, `recall_with_confidence`, `u_shape`, `order_for_prompt` to the imports and `__all__`, keeping isort order (run `ruff check --fix` on the file).

- [ ] **Step 8: Add the `gate` benchmark variant**

In `benchmark_rag_quality.py` change `recall_ranker` to accept a keyword `gate: GateConfig | None = None` after `embedder`; when set, `rank` calls `recall_with_confidence(..., gate=gate)` and returns `[id_by_text[h.text] for h in result.hits]`. In `run()` add:

```python
    with recall_ranker(passages, gate=GateConfig(enabled=True)) as gated:
        variants["gate"] = evaluate(gated, queries, k)
```

(import `GateConfig` and `recall_with_confidence`).

- [ ] **Step 9: Run tests, lint, format, and calibrate**

Run: `uv run --extra dev ruff format src tests Agents/benchmark && uv run --extra dev ruff check --fix src tests Agents/benchmark && uv run --extra dev pytest tests/test_rag_gate.py Agents/benchmark/Tasks/rag_quality tests/test_rag_ordering.py -q`
Expected: all pass. Then run the benchmark and add the `gate` row to the spec's Results.
Calibration rule: the thresholds `high=0.5`, `low=0.2` are starting values. If `gate` loses answerable-query recall@3 against `baseline`, lower `low` in steps of 0.05 and rerun; keep the largest `low` that preserves recall@3 and MRR while `false_inject_rate` stays 0.0, and record the chosen values and the grid tried in the spec. If no value satisfies both, the gate stays default-off and the spec records that.

---

### Task 5: Parent-child chunking

**Files:**
- Modify: `src/swarm_sdk/retrieval/rag_ingest.py` (add `split_children`; `child_size` parameter; parent registry; query grouping; persistence)
- Modify: `src/swarm_sdk/cli.py:379` (pass `child_size` from config)
- Modify: `Agents/benchmark/Tasks/rag_quality/benchmark_rag_quality.py` (pipeline variants)
- Test: `tests/test_rag_parent_child.py`, extend `Agents/benchmark/Tasks/rag_quality/test_rag_quality.py`

**Interfaces:**
- Produces: `split_children(content: str, child_size: int) -> list[str]` (module-level in `rag_ingest.py`); `RAGIngestionPipeline(..., child_size: int | None = None)` (`ValueError` when below 1); in child mode `self.chunks` holds children whose `metadata` has `parent_id` and `child_index`, `self._parents: dict[str, DocumentChunk]` holds parents, and `query()` returns parents deduplicated by `parent_id` with the best child score.
- Consumes: `RagConfig.parent_child`, `RagConfig.child_size` (Task 3), `load_swarm_config()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_rag_parent_child.py`:

```python
"""Parent-child (small-to-big) chunking in RAGIngestionPipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmark.Tasks.rag_quality.embedders import BagOfWordsEmbedder
from swarm_sdk.retrieval.rag_ingest import RAGIngestionPipeline, split_children

DOC = (
    "# Guide\n\n## Cache\n\n"
    "The semantic cache stores answers. Entries expire after days. "
    "Empty answers are never cached. Lookups use cosine similarity.\n\n"
    "## Vault\n\nKeys live in the Keychain and never in YAML files.\n"
)


def test_split_children_respects_size_and_preserves_words() -> None:
    text = "one two three four five six seven"
    parts = split_children(text, 10)
    assert all(len(p) <= 10 for p in parts)
    assert " ".join(parts).split() == text.split()


def test_split_children_edge_cases() -> None:
    assert split_children("", 10) == []
    assert split_children("   ", 10) == []
    assert split_children("abcdefghijklmnop", 5) == ["abcdefghijklmnop"]  # one long word stays whole
    assert split_children("café 東京 ß", 6) == ["café", "東京 ß"]
    with pytest.raises(ValueError):
        split_children("x", 0)


def test_child_size_must_be_positive() -> None:
    with pytest.raises(ValueError):
        RAGIngestionPipeline(child_size=0)


def test_default_pipeline_is_unchanged() -> None:
    pipeline = RAGIngestionPipeline(force_numpy=True)
    n = pipeline.ingest_text(DOC)
    assert len(pipeline.chunks) == n
    assert all("parent_id" not in c.metadata for c in pipeline.chunks)


def test_children_are_indexed_but_parents_are_returned() -> None:
    pipeline = RAGIngestionPipeline(embedder=BagOfWordsEmbedder(), child_size=40, force_numpy=True)
    pipeline.ingest_text(DOC)
    assert len(pipeline.chunks) > len(pipeline._parents)
    results = pipeline.query("empty answers cached", top_k=2)
    parent_ids = [r.chunk.chunk_id for r in results]
    assert len(parent_ids) == len(set(parent_ids))  # deduplicated by parent
    assert "Empty answers are never cached" in results[0].chunk.content
    assert len(results[0].chunk.content) > 40  # the full parent, not the child


def test_reingesting_the_same_source_does_not_collide() -> None:
    pipeline = RAGIngestionPipeline(child_size=40, force_numpy=True)
    pipeline.ingest_text(DOC, source_file="a.md")
    after_first = len(pipeline._parents)
    pipeline.ingest_text(DOC, source_file="a.md")
    assert after_first > 0
    assert len(pipeline._parents) == 2 * after_first  # no id reuse across ingests


def test_save_and_load_round_trip_returns_the_same_parents(tmp_path: Path) -> None:
    embedder = BagOfWordsEmbedder()
    pipeline = RAGIngestionPipeline(embedder=embedder, child_size=40, force_numpy=True)
    pipeline.ingest_text(DOC)
    expected = [r.chunk.content for r in pipeline.query("keychain yaml", top_k=2)]
    assert expected
    pipeline.save(tmp_path)
    restored = RAGIngestionPipeline(embedder=embedder, child_size=40, force_numpy=True)
    restored.load(tmp_path)
    assert [r.chunk.content for r in restored.query("keychain yaml", top_k=2)] == expected


def test_empty_query_and_empty_pipeline_return_nothing() -> None:
    pipeline = RAGIngestionPipeline(embedder=BagOfWordsEmbedder(), child_size=40, force_numpy=True)
    assert pipeline.query("anything") == []
    pipeline.ingest_text(DOC)
    assert pipeline.query("   ") == []
```

Append to `Agents/benchmark/Tasks/rag_quality/test_rag_quality.py`:

```python
def test_pipeline_variants_are_reported() -> None:
    report = run()
    assert {"pipeline_flat", "pipeline_parent_child"} <= set(report["variants"])
    for name in ("pipeline_flat", "pipeline_parent_child"):
        assert all(0.0 <= v <= 1.0 for v in report["variants"][name].values())
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest tests/test_rag_parent_child.py -q`
Expected: FAIL, `ImportError: cannot import name 'split_children'`.

- [ ] **Step 3: Implement in `rag_ingest.py`**

Add the module-level function after `RetrievalResult`:

```python
def split_children(content: str, child_size: int) -> list[str]:
    """Split ``content`` into whitespace-aligned pieces of at most ``child_size`` characters.

    A single word longer than ``child_size`` is kept whole rather than cut.

    Raises:
        ValueError: If ``child_size`` is below 1.
    """
    if child_size < 1:
        raise ValueError("child_size must be >= 1")
    parts: list[str] = []
    current: list[str] = []
    length = 0
    for word in content.split():
        extra = len(word) + (1 if current else 0)
        if current and length + extra > child_size:
            parts.append(" ".join(current))
            current, length = [word], len(word)
        else:
            current.append(word)
            length += extra
    if current:
        parts.append(" ".join(current))
    return parts
```

In `RAGIngestionPipeline.__init__` add keyword `child_size: int | None = None`; after the signature body start:

```python
        if child_size is not None and child_size < 1:
            raise ValueError("child_size must be >= 1")
        self.child_size = child_size
        self._parents: dict[str, DocumentChunk] = {}
```

Add the method:

```python
    def _index_units(self, parents: list[DocumentChunk]) -> list[DocumentChunk]:
        """Return the chunks to embed: the parents, or their children in parent-child mode."""
        if self.child_size is None:
            return parents
        units: list[DocumentChunk] = []
        for parent in parents:
            parent_id = f"{parent.chunk_id}@{len(self._parents)}"
            self._parents[parent_id] = parent
            pieces = split_children(parent.content, self.child_size) or [parent.content]
            for index, piece in enumerate(pieces):
                full = f"{parent.header_context}\n{piece}" if parent.header_context else piece
                units.append(
                    DocumentChunk(
                        chunk_id=f"{parent_id}#c{index}",
                        source_file=parent.source_file,
                        header_context=parent.header_context,
                        content=piece,
                        full_text=full,
                        metadata={**parent.metadata, "parent_id": parent_id, "child_index": index},
                    )
                )
        return units
```

In `ingest_text` and `ingest_files`, replace the line that builds `full_texts` from `chunks` / `all_new_chunks` so the units are used. For `ingest_text`:

```python
        chunks = self._index_units(chunks)
        full_texts = [c.full_text for c in chunks]
```

placed right after the `if not chunks: return 0` check (the return value stays `len(chunks)`, now the number of indexed units). Apply the same `all_new_chunks = self._index_units(all_new_chunks)` after the `if not all_new_chunks: return 0` check in `ingest_files`.

Replace the body of `query` from `k = min(top_k, ...)` on:

```python
        k = min(top_k, len(self.chunks))
        if k <= 0:
            return []
        if self.child_size is not None:
            k = min(len(self.chunks), top_k * 4)  # over-fetch so top_k distinct parents survive

        q_vec = self._embed([cleaned], query=True)
        scores, indices = self.index.search(q_vec, k)

        results: list[RetrievalResult] = []
        seen_parents: set[str] = set()
        for score, idx in zip(scores[0], indices[0], strict=False):
            if idx < 0 or idx >= len(self.chunks):
                continue
            chunk = self.chunks[idx]
            parent_id = chunk.metadata.get("parent_id")
            if parent_id is not None and parent_id in self._parents:
                if parent_id in seen_parents:
                    continue  # results arrive best-first, so the first child wins
                seen_parents.add(parent_id)
                chunk = self._parents[parent_id]
            results.append(RetrievalResult(chunk=chunk, score=float(score)))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]
```

`save`: after the chunks.json write add:

```python
        if self._parents:
            (target_dir / "parents.json").write_text(
                json.dumps({k: v.model_dump() for k, v in self._parents.items()}, ensure_ascii=False),
                encoding="utf-8",
            )
```

`load`: after `self.chunks = [...]` add:

```python
        parents_file = target_dir / "parents.json"
        self._parents = (
            {
                k: DocumentChunk.model_validate(v)
                for k, v in json.loads(parents_file.read_text(encoding="utf-8")).items()
            }
            if parents_file.exists()
            else {}
        )
```

Note: `ingest_text` previously returned `len(chunks)` before indexing; keep returning the indexed-unit count and let the default-mode test confirm `len(pipeline.chunks) == n`.

- [ ] **Step 4: Wire the CLI**

In `src/swarm_sdk/cli.py` `handle_ingest`, replace `pipeline = RAGIngestionPipeline()` with:

```python
    rag = load_swarm_config().rag
    pipeline = RAGIngestionPipeline(child_size=rag.child_size if rag.parent_child else None)
```

and add `from swarm_sdk.config.loader import load_swarm_config` to the imports (isort order).

- [ ] **Step 5: Add the pipeline variants to the benchmark**

In `benchmark_rag_quality.py` add:

```python
@contextmanager
def pipeline_ranker(passages: Sequence[Passage], *, child_size: int | None) -> Iterator[Ranker]:
    """Yield a ranker over ``RAGIngestionPipeline`` built from one Markdown section per passage."""
    pipeline = RAGIngestionPipeline(
        embedder=BagOfWordsEmbedder(DIM), child_size=child_size, force_numpy=True
    )
    document = "\n\n".join(f"## {p.id}\n\n{p.text}" for p in passages)
    pipeline.ingest_text(document)
    id_by_text = {p.text: p.id for p in passages}

    def rank(query: str) -> list[str]:
        results = pipeline.query(query, top_k=RERANK_K)
        return [id_by_text[r.chunk.content.strip()] for r in results]

    yield rank
```

(import `RAGIngestionPipeline`; the `@contextmanager` is kept for symmetry with `recall_ranker`.) In `run()` add:

```python
    with pipeline_ranker(passages, child_size=None) as flat:
        variants["pipeline_flat"] = evaluate(flat, queries, k)
    with pipeline_ranker(passages, child_size=40) as nested:
        variants["pipeline_parent_child"] = evaluate(nested, queries, k)
```

If `id_by_text[...]` raises `KeyError` because the chunker joined or altered passage text, print `pipeline.chunks[0].content` and map on the chunk's `header_context` (the section id) instead; do not weaken the lookup with `.get`.

- [ ] **Step 6: Run tests, lint, format, record**

Run: `uv run --extra dev ruff format src tests Agents/benchmark && uv run --extra dev ruff check --fix src tests Agents/benchmark && uv run --extra dev pytest tests/test_rag_parent_child.py tests/test_rag_ingest.py Agents/benchmark/Tasks/rag_quality -q`
Expected: all pass, including the existing `tests/test_rag_ingest.py` (default mode unchanged). Then run the benchmark and add both `pipeline_*` rows to the spec's Results.

---

### Task 6: Decide defaults, document, full gate

**Files:**
- Modify: `docs/superpowers/specs/2026-10-02-rag-techniques-design.md` (Results, final decisions)
- Modify: `README.md` (one short subsection under the existing configuration or retrieval docs; locate with `rg -n 'hybrid|rerank' README.md`)
- Modify: `src/swarm_sdk/agents/config/swarm.yaml` (set a flag to `true` only where the acceptance rule allows)

- [ ] **Step 1: Apply the acceptance rule**

From the benchmark table in the spec: set `rag.gate.enabled: true` in `swarm.yaml` only if the `gate` row has `false_inject_rate == 0.0` and recall@3 and MRR are not below `baseline`. Set `rag.parent_child: true` only if `pipeline_parent_child` has recall@3 or MRR above `pipeline_flat` and neither below. `u_shape_order` stays `false` by default (it is judged by the prompt-assembly test, not the retrieval metrics) unless you decide otherwise. For each technique, write one line in the spec's Results: keep or keep-off, with the numbers.

- [ ] **Step 2: Document**

Add to `README.md` a short "RAG options" block listing the three flags, their defaults, the gate's per-reranker threshold note, and the benchmark command `cd Agents && uv run python -m benchmark.Tasks.rag_quality.benchmark_rag_quality`.

- [ ] **Step 3: Full gate, once**

Run:
`uv run --extra dev ruff format --check src Agents/benchmark Main`
`uv run --extra dev ruff check src Agents/benchmark Main`
`uv run python -m compileall -q src Agents Main`
`uv run --extra dev pytest -q`
`uv run python -m swarm_sdk.agents.validate`
Expected: all clean/pass. Report any failure with its output; do not weaken a check.

- [ ] **Step 4: Report**

Report what changed, the final benchmark table, which flags ship on or off and why, what was not run (`ty`), and the rollback: delete the new files (`ordering.py`, `gate.py`, `Tasks/rag_quality/`, the three `tests/test_rag_*.py`) and `git checkout` the modified files, noting that several already carried uncommitted edits.
