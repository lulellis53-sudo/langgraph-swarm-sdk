"""The graph's researcher node reads from the shared multi-agent store."""

from __future__ import annotations

from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from orchestration.agent_rag import ingest_agents, make_search
from orchestration.embedding import HashEmbedder
from orchestration.graph import build_graph
from orchestration.graphic import write_graph_files
from orchestration.vectorstore import SharedVectorStore


def test_researcher_uses_the_shared_store_and_graph_is_drawn(tmp_path: Path) -> None:
    (tmp_path / "agents" / "RAG").mkdir(parents=True)
    (tmp_path / "agents" / "RAG" / "AGENTS.md").write_text(
        "# Retrieval\n\nFAISS vector index with reranking.\n", encoding="utf-8"
    )
    (tmp_path / "agents" / "Coder").mkdir()
    (tmp_path / "agents" / "Coder" / "AGENTS.md").write_text(
        "# Coder\n\nWrite python and run pytest.\n", encoding="utf-8"
    )
    embedder = HashEmbedder(dim=256)
    store = SharedVectorStore(dim=embedder.dim)
    ingest_agents(tmp_path / "agents", store, embedder)
    store.save(tmp_path / "idx")
    reloaded = SharedVectorStore.load(tmp_path / "idx")

    graph = build_graph(
        FakeListChatModel(responses=["faiss vector index", "final answer"]),
        make_search(reloaded, embedder, agent="RAG", k=2),
    )
    result = graph.invoke({"goal": "how do we index vectors?"})

    assert "FAISS vector index" in result["research"]
    assert "Coder/" not in result["research"]
    assert result["answer"] == "final answer"
    names = [p.name for p in write_graph_files(graph, tmp_path / "docs")]
    assert names == ["graph.mmd", "graph.md"]
