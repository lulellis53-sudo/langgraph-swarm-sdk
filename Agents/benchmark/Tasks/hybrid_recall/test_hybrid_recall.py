import json
from pathlib import Path

import pytest

from swarm_sdk.config.loader import load_swarm_config
from swarm_sdk.memory.sqlite_vec import SqliteVecStore
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.recall import recall_texts
from swarm_sdk.retrieval.rerank import KeywordReranker


@pytest.mark.asyncio
async def test_hybrid_recall(tmp_path: Path) -> None:
    store = SqliteVecStore(str(tmp_path / "m.db"), dim=32)
    embedder = HashEmbedder(32, model_name="sentence-transformers/all-MiniLM-L6-v2")
    fixture = Path(__file__).parent / "fixtures" / "memories.jsonl"
    for line in fixture.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        text = json.loads(line)["text"]
        vector = embedder.embed([text], query=False)[0]
        store.add(text, vector)

    cfg = load_swarm_config()
    snippets = recall_texts(
        "sqlite vec int8 memory",
        store,
        embedder,
        KeywordReranker(),
        retrieve_k=3,
        rerank_k=2,
        dedup_threshold=0.99,
        hybrid=cfg.hybrid_search,
        hybrid_enabled=True,
    )
    assert snippets
    assert any("sqlite" in s.lower() for s in snippets)
    store.close()
