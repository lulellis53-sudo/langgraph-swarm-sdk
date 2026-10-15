"""Ingest and retrieve sample documents through the configured RAG tools."""

from langswarm.tools import get_tool


def main() -> None:
    ingest = get_tool("rag_ingest")
    search = get_tool("rag_search")
    facts = [
        "Langswarm is a thirteen-agent swarm built on LangGraph and langgraph-swarm.",
        "The default vector backend is local FAISS with CPU embeddings.",
        "Checkpointers support in-memory, SQLite, and Redis conversation state.",
    ]
    for fact in facts:
        print(ingest(fact, source="example"))
    print(search("What vector backend does Langswarm use by default?"))


if __name__ == "__main__":
    main()
