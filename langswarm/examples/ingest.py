"""Ingestion example demonstrating vector RAG knowledge base population."""

from __future__ import annotations

import asyncio

from langswarm.retrieval import get_retrieval_backend


async def main() -> None:
    """Ingest sample data into the default FAISS vector backend."""
    retriever = get_retrieval_backend()

    sample_docs = [
        "LangSwarm is a twelve-agent swarm built on LangGraph 1.x and langgraph-swarm.",
        "The default vector backend uses local FAISS with FastEmbed ONNX embeddings on CPU.",
        "Checkpointer support includes In-Memory, SQLite, and Redis checkpoints.",
        "Long-term memory is backed by the Mem0 platform API with automatic caching.",
    ]

    print("Ingesting sample documents into FAISS vector store...")
    await retriever.aingest(sample_docs)
    print("Ingestion complete.")

    query = "What is the default vector backend in LangSwarm?"
    print(f"\nSearching for: '{query}'")
    results = await retriever.asearch(query, k=2)
    for i, res in enumerate(results, 1):
        print(f"[{i}] {res}")


if __name__ == "__main__":
    asyncio.run(main())
