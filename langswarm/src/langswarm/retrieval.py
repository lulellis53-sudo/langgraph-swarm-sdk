"""RAG retrieval over two interchangeable vector backends.

- ``faiss`` (default): fully local and infrastructure-free. Embeddings via
  fastembed on onnxruntime, index via faiss-cpu, persisted to a folder.
- ``pgvector``: Postgres with the pgvector extension via langchain-postgres
  (``postgres`` extra), for durable multi-process deployments.

Both consume the same FastEmbeddings, so the Researcher and Archivist tools
work unchanged on either backend.
"""

_store = None


def build_vectorstore(backend: str | None = None):
    """Return (and cache for the process) the vector store for the backend."""
    global _store
    if _store is not None:
        return _store

    from langswarm.config import settings
    from langswarm.embeddings import FastEmbeddings

    backend = (backend or settings.vector_backend).lower()
    embeddings = FastEmbeddings(model_name=settings.embedding_model)

    if backend == "faiss":
        from langchain_community.vectorstores import FAISS

        try:
            _store = FAISS.load_local(
                settings.faiss_path, embeddings, allow_dangerous_deserialization=True
            )
        except Exception:
            _store = FAISS.from_texts(
                ["Langswarm knowledge base initialized."], embeddings
            )
        return _store

    if backend == "pgvector":
        try:
            from langchain_postgres import PGVector
        except ImportError as error:
            raise RuntimeError(
                "The 'postgres' extra is required for the pgvector backend."
            ) from error

        _store = PGVector(
            embeddings=embeddings,
            collection_name=settings.pgvector_collection,
            connection=settings.pgvector_connection,
            use_jsonb=True,
        )
        return _store

    raise ValueError(
        f"Unknown vector backend {backend!r}; expected 'faiss' or 'pgvector'."
    )


def rag_search_tool(*, k: int = 4):
    """Return the knowledge-base search tool used by the Researcher."""

    def search(query: str) -> str:
        """Search the knowledge base and return the most relevant passages."""
        hits = build_vectorstore().similarity_search(query, k=k)
        if not hits:
            return "No relevant passages were found in the knowledge base."
        return "\n\n".join(
            f"[{i}] {doc.page_content}" for i, doc in enumerate(hits, start=1)
        )

    return search


def rag_ingest_tool():
    """Return the ingestion tool used by the Archivist."""

    def ingest(content: str, source: str = "manual") -> str:
        """Add a document to the knowledge base for future retrieval."""
        from langchain_core.documents import Document

        from langswarm.config import settings

        store = build_vectorstore()
        ids = store.add_documents(
            [Document(page_content=content, metadata={"source": source})]
        )
        if settings.vector_backend == "faiss":
            store.save_local(settings.faiss_path)
        return f"Indexed {len(ids)} document into the knowledge base."

    return ingest
