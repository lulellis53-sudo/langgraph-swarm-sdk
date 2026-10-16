"""Each subfolder of the agents root is one agent's RAG inside the shared store."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestration.agent_rag import chunk_markdown, ingest_agents, make_search
from orchestration.embedding import HashEmbedder
from orchestration.vectorstore import SharedVectorStore


@pytest.fixture
def agents_root(tmp_path: Path) -> Path:
    (tmp_path / "Coder").mkdir()
    (tmp_path / "Coder" / "AGENTS.md").write_text(
        "# Coder\n\nWrite python code and run pytest.\n\n## Style\n\nUse ruff and type hints.\n",
        encoding="utf-8",
    )
    (tmp_path / "RAG" / "notes").mkdir(parents=True)
    (tmp_path / "RAG" / "notes" / "faiss.md").write_text(
        "# Retrieval\n\nFAISS vector index with reranking.\n", encoding="utf-8"
    )
    (tmp_path / "_shared").mkdir()
    (tmp_path / "_shared" / "COMMON.md").write_text("# Common\n\nignored\n", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "x.md").write_text("# H\n\nhidden\n", encoding="utf-8")
    return tmp_path


def test_chunk_markdown_splits_on_headings_and_caps_length() -> None:
    chunks = chunk_markdown("# A\n\none\n\n## B\n\ntwo\n", max_chars=1200)
    assert len(chunks) == 2 and chunks[0].startswith("# A") and chunks[1].startswith("## B")
    long = chunk_markdown("x" * 50, max_chars=20)
    assert all(len(c) <= 20 for c in long) and "".join(long) == "x" * 50


def test_chunk_markdown_blank_input_gives_no_chunks() -> None:
    assert chunk_markdown("") == [] and chunk_markdown("  \n\n ") == []


def test_ingest_uses_one_store_one_slot_per_agent_folder(agents_root: Path) -> None:
    store = SharedVectorStore(dim=128)
    added = ingest_agents(agents_root, store, HashEmbedder(dim=128))
    assert set(added) == {"Coder", "RAG"}
    assert set(store.agents()) == {"Coder", "RAG"}
    assert store.count("RAG") == added["RAG"] >= 1


def test_ingest_is_idempotent(agents_root: Path) -> None:
    store = SharedVectorStore(dim=128)
    embedder = HashEmbedder(dim=128)
    ingest_agents(agents_root, store, embedder)
    total = store.count()
    assert sum(ingest_agents(agents_root, store, embedder).values()) == 0
    assert store.count() == total


def test_ingest_skips_empty_and_non_utf8_files(agents_root: Path) -> None:
    (agents_root / "Coder" / "empty.md").write_text("", encoding="utf-8")
    (agents_root / "Coder" / "bad.md").write_bytes(b"\xff\xfe\x00bad")
    store = SharedVectorStore(dim=128)
    embedder = HashEmbedder(dim=128)
    ingest_agents(agents_root, store, embedder)
    sources = {h.source for h in store.search(embedder.embed(["code"])[0], k=20)}
    assert sources == {"Coder/AGENTS.md", "RAG/notes/faiss.md"}


def test_ingest_does_not_follow_symlinked_folders(
    agents_root: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.md").write_text("# S\n\noutside secret\n", encoding="utf-8")
    (agents_root / "Linked").symlink_to(outside, target_is_directory=True)
    store = SharedVectorStore(dim=128)
    ingest_agents(agents_root, store, HashEmbedder(dim=128))
    assert "Linked" not in store.agents()


def test_make_search_filters_by_agent_and_handles_empty_query(agents_root: Path) -> None:
    store = SharedVectorStore(dim=128)
    embedder = HashEmbedder(dim=128)
    ingest_agents(agents_root, store, embedder)
    only_rag = make_search(store, embedder, agent="RAG", k=3)("faiss vector index")
    assert only_rag.startswith("[RAG/") and "Coder/" not in only_rag
    everyone = make_search(store, embedder, k=5)("python pytest ruff faiss")
    assert "Coder/" in everyone and "RAG/" in everyone
    assert make_search(store, embedder)("   ") == ""
