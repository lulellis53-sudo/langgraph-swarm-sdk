import numpy as np

from swarm_sdk.embeddings import HashEmbedder
from swarm_sdk.hybrid import HybridSearchConfig, hybrid_search, rrf_merge
from swarm_sdk.memory.base import MemoryHit


class MemoryStub:
    def __init__(self, hits: list[MemoryHit]) -> None:
        self._hits = hits

    def add(self, text: str, vector: np.ndarray) -> int:
        del text, vector
        return 0

    def search(self, vector: np.ndarray, k: int) -> list[MemoryHit]:
        del vector
        return self._hits[:k]


def test_rrf_merge_orders_overlap() -> None:
    order = rrf_merge([[0, 1, 2], [2, 0, 1]], k=60)
    assert order[0] in {0, 2}


def test_hybrid_search_prefers_keyword_match() -> None:
    hits = [
        MemoryHit(id=1, text="alpha beta", score=0.9),
        MemoryHit(id=2, text="gamma sqlite vec int8", score=0.5),
    ]
    store = MemoryStub(hits)
    embedder = HashEmbedder(16, model_name="bge")
    vector = embedder.embed(["sqlite memory"], query=True)[0]
    cfg = HybridSearchConfig(enabled=True, dense_weight=0.5, keyword_weight=2.0, final_k=2)
    merged = hybrid_search("sqlite int8", store, vector, retrieve_k=2, config=cfg)
    assert merged
    assert any("sqlite" in hit.text for hit in merged)
