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

from benchmark.Tasks.rag_quality.embedders import BagOfWordsEmbedder
from benchmark.Tasks.rag_quality.metrics import mrr, recall_at_k
from swarm_sdk.memory.sqlite_vec import SqliteVecStore
from swarm_sdk.retrieval.embeddings import Embedder
from swarm_sdk.retrieval.gate import GateConfig
from swarm_sdk.retrieval.hybrid import HybridSearchConfig
from swarm_sdk.retrieval.rag_ingest import RAGIngestionPipeline
from swarm_sdk.retrieval.recall import recall_hits, recall_with_confidence
from swarm_sdk.retrieval.rerank import KeywordReranker

FIXTURES = Path(__file__).parent / "fixtures"
DIM = 256
RETRIEVE_K = 8
RERANK_K = 4

type Ranker = Callable[[str], list[str]]


@dataclass(frozen=True, slots=True)
class Passage:
    """One corpus passage with its id and text."""

    id: str
    text: str


@dataclass(frozen=True, slots=True)
class Query:
    """One query with the ids of the passages that are relevant to it."""

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
    passages: Sequence[Passage],
    embedder: Embedder | None = None,
    *,
    gate: GateConfig | None = None,
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
            common = {
                "retrieve_k": RETRIEVE_K,
                "rerank_k": RERANK_K,
                "dedup_threshold": 0.99,
                "hybrid": hybrid,
                "hybrid_enabled": True,
            }
            if gate is None:
                hits = recall_hits(query, store, embedder, reranker, **common)
            else:
                hits = recall_with_confidence(
                    query, store, embedder, reranker, gate=gate, **common
                ).hits
            return [id_by_text[hit.text] for hit in hits]

        try:
            yield rank
        finally:
            store.close()


@contextmanager
def pipeline_ranker(passages: Sequence[Passage], *, child_size: int | None) -> Iterator[Ranker]:
    """Yield a ranker over ``RAGIngestionPipeline`` built from one Markdown section per passage."""
    pipeline = RAGIngestionPipeline(
        embedder=BagOfWordsEmbedder(DIM), child_size=child_size, force_numpy=True
    )
    pipeline.ingest_text("\n\n".join(f"## {p.id}\n\n{p.text}" for p in passages))
    id_by_text = {p.text: p.id for p in passages}

    def rank(query: str) -> list[str]:
        results = pipeline.query(query, top_k=RERANK_K)
        return [id_by_text[r.chunk.content.strip()] for r in results]

    yield rank


def run(*, k: int = 3) -> dict[str, Any]:
    """Run every variant and return the metric table."""
    passages, queries = load_fixture()
    variants: dict[str, dict[str, float]] = {}
    with recall_ranker(passages) as baseline:
        variants["baseline"] = evaluate(baseline, queries, k)
    with recall_ranker(passages, gate=GateConfig(enabled=True)) as gated:
        variants["gate"] = evaluate(gated, queries, k)
    with pipeline_ranker(passages, child_size=None) as flat:
        variants["pipeline_flat"] = evaluate(flat, queries, k)
    with pipeline_ranker(passages, child_size=40) as nested:
        variants["pipeline_parent_child"] = evaluate(nested, queries, k)
    return {"k": k, "n_passages": len(passages), "n_queries": len(queries), "variants": variants}


def format_table(report: dict[str, Any]) -> str:
    lines = [f"{'variant':<22}{'recall@k':>10}{'mrr':>8}{'false_inject':>14}"]
    for name, row in report["variants"].items():
        lines.append(
            f"{name:<22}{row['recall_at_k']:>10.3f}{row['mrr']:>8.3f}"
            f"{row['false_inject_rate']:>14.3f}"
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
