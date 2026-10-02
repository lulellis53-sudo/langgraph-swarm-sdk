"""RAG ingestion pipeline with contextual markdown chunking, FAISS index, and NumPy fallback."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from swarm_sdk.retrieval.embeddings import Embedder, HashEmbedder

logger = logging.getLogger(__name__)

try:
    import faiss

    _FAISS_AVAILABLE = True
except ImportError:  # pragma: no cover
    faiss = None
    _FAISS_AVAILABLE = False


class DocumentChunk(BaseModel):
    """A semantically bounded chunk of a document with contextual metadata."""

    chunk_id: str
    source_file: str
    header_context: str
    content: str
    full_text: str  # header_context + "\n" + content
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    """Ranked retrieval candidate with similarity score."""

    chunk: DocumentChunk
    score: float


class _NumpyVectorStore:
    """In-memory vector store using NumPy dot-product for cosine similarity."""

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.vectors: np.ndarray = np.empty((0, dim), dtype=np.float32)

    def add(self, vectors: np.ndarray) -> None:
        if vectors.size == 0:
            return
        arr = np.asarray(vectors, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        if self.vectors.size == 0:
            self.vectors = arr
        else:
            self.vectors = np.vstack([self.vectors, arr])

    def search(self, query_vector: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
        """Search top-k nearest neighbors by cosine similarity."""
        if len(self.vectors) == 0:
            return np.empty((1, 0), dtype=np.float32), np.empty((1, 0), dtype=np.int64)
        query = np.asarray(query_vector, dtype=np.float32).reshape(1, -1)
        # Assuming query and self.vectors are L2-normalized:
        scores = np.dot(self.vectors, query.T).reshape(-1)
        k = min(k, len(scores))
        if k <= 0:
            return np.empty((1, 0), dtype=np.float32), np.empty((1, 0), dtype=np.int64)
        top_indices = np.argsort(-scores)[:k]
        top_scores = scores[top_indices]
        return top_scores.reshape(1, -1), top_indices.reshape(1, -1)

    @property
    def ntotal(self) -> int:
        return len(self.vectors)


class RAGIngestionPipeline:
    """End-to-end RAG ingestion and retrieval pipeline.

    Features:
    - Contextual Markdown chunking preserving header hierarchy.
    - Vector embeddings via custom or HashEmbedder.
    - Indexing using FAISS IndexFlatIP (cosine similarity) with seamless
      NumPy fallback (_NumpyVectorStore).
    - Disk persistence and cross-backend restoration.
    """

    def __init__(
        self,
        embedding_dim: int = 128,
        embedder: Any = None,
        *,
        force_numpy: bool = False,
    ) -> None:
        self.embedding_dim = embedding_dim
        self._force_numpy = force_numpy
        if embedder is not None:
            self.embedder = embedder
            if hasattr(embedder, "dim"):
                self.embedding_dim = int(embedder.dim)
        else:
            self.embedder = HashEmbedder(dim=self.embedding_dim)

        self.chunks: list[DocumentChunk] = []
        self._init_index()

    def _init_index(self) -> None:
        """Initialize the vector index with FAISS or fallback to NumPy."""
        if not self._force_numpy and _FAISS_AVAILABLE and faiss is not None:
            try:
                self.index = faiss.IndexFlatIP(self.embedding_dim)
                self._is_faiss = True
                return
            except Exception as exc:  # pragma: no cover
                logger.warning("FAISS initialization failed (%s); falling back to NumPy", exc)
        self.index = _NumpyVectorStore(self.embedding_dim)
        self._is_faiss = False

    def _embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        """Generate L2-normalized embeddings for passages or queries."""
        if not texts:
            return np.zeros((0, self.embedding_dim), dtype=np.float32)
        try:
            vecs = self.embedder.embed(texts, query=query)
        except TypeError:
            vecs = self.embedder.embed(texts)
        arr = np.asarray(vecs, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        # Normalize vectors so dot-product equals cosine similarity
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return np.ascontiguousarray(arr / norms, dtype=np.float32)

    def chunk_markdown(
        self,
        text: str,
        source_file: str = "",
        max_chunk_size: int = 1500,
    ) -> list[DocumentChunk]:
        """Split Markdown document into contextual chunks with section hierarchy."""
        lines = text.splitlines()
        chunks: list[DocumentChunk] = []
        header_stack: list[tuple[int, str]] = []  # (level, title)
        current_body: list[str] = []
        in_code_block = False

        header_re = re.compile(r"^(#{1,6})\s+(.+)$")
        chunk_idx = 0

        def emit_section(headers: list[tuple[int, str]], body_lines: list[str]) -> None:
            nonlocal chunk_idx
            raw_content = "\n".join(body_lines).strip()
            if not raw_content:
                return

            header_context = " > ".join(title for _, title in headers)

            # If section content exceeds max_chunk_size, split by paragraphs
            paragraphs = raw_content.split("\n\n")
            current_part: list[str] = []
            current_len = 0

            for p in paragraphs:
                p_str = p.strip()
                if not p_str:
                    continue
                if current_part and (current_len + len(p_str) + 2 > max_chunk_size):
                    part_content = "\n\n".join(current_part)
                    full_text = (
                        f"{header_context}\n{part_content}" if header_context else part_content
                    )
                    chunk_id = f"{source_file}:{chunk_idx}" if source_file else f"chunk_{chunk_idx}"
                    chunks.append(
                        DocumentChunk(
                            chunk_id=chunk_id,
                            source_file=source_file,
                            header_context=header_context,
                            content=part_content,
                            full_text=full_text,
                            metadata={
                                "chunk_index": chunk_idx,
                                "source_file": source_file,
                                "headers": [t for _, t in headers],
                            },
                        )
                    )
                    chunk_idx += 1
                    current_part = [p_str]
                    current_len = len(p_str)
                else:
                    current_part.append(p_str)
                    current_len += len(p_str) + 2

            if current_part:
                part_content = "\n\n".join(current_part)
                full_text = f"{header_context}\n{part_content}" if header_context else part_content
                chunk_id = f"{source_file}:{chunk_idx}" if source_file else f"chunk_{chunk_idx}"
                chunks.append(
                    DocumentChunk(
                        chunk_id=chunk_id,
                        source_file=source_file,
                        header_context=header_context,
                        content=part_content,
                        full_text=full_text,
                        metadata={
                            "chunk_index": chunk_idx,
                            "source_file": source_file,
                            "headers": [t for _, t in headers],
                        },
                    )
                )
                chunk_idx += 1

        for line in lines:
            stripped = line.strip()
            # Toggle code block state
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_code_block = not in_code_block
                current_body.append(line)
                continue

            if not in_code_block:
                m = header_re.match(stripped)
                if m:
                    # Flush pending section under previous header hierarchy
                    emit_section(header_stack, current_body)
                    current_body = []

                    level = len(m.group(1))
                    title = m.group(2).strip().strip("#").strip()
                    # Pop headers of equal or deeper level
                    while header_stack and header_stack[-1][0] >= level:
                        header_stack.pop()
                    header_stack.append((level, title))
                    continue

            current_body.append(line)

        # Flush trailing section
        emit_section(header_stack, current_body)
        return chunks

    def ingest_text(self, text: str, source_file: str = "text") -> int:
        """Chunk a text string, generate embeddings, and index them."""
        chunks = self.chunk_markdown(text, source_file=source_file)
        if not chunks:
            return 0
        full_texts = [c.full_text for c in chunks]
        vectors = self._embed(full_texts, query=False)
        self.index.add(vectors)
        self.chunks.extend(chunks)
        return len(chunks)

    def ingest_files(self, paths: list[str | Path]) -> int:
        """Chunk documents from file paths, compute embeddings, and index them."""
        all_new_chunks: list[DocumentChunk] = []

        for p in paths:
            path = Path(p)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")

            if path.is_dir():
                md_files = sorted(path.glob("**/*.md"))
                for md in md_files:
                    content = md.read_text(encoding="utf-8")
                    all_new_chunks.extend(self.chunk_markdown(content, source_file=str(md)))
            else:
                content = path.read_text(encoding="utf-8")
                all_new_chunks.extend(self.chunk_markdown(content, source_file=str(path)))

        if not all_new_chunks:
            return 0

        full_texts = [c.full_text for c in all_new_chunks]
        vectors = self._embed(full_texts, query=False)
        self.index.add(vectors)
        self.chunks.extend(all_new_chunks)
        return len(all_new_chunks)

    def query(self, query_text: str, top_k: int = 5) -> list[RetrievalResult]:
        """Embed query and return top-k ranked RetrievalResult items sorted by score."""
        cleaned = query_text.strip()
        if not cleaned or not self.chunks:
            return []

        k = min(top_k, len(self.chunks))
        if k <= 0:
            return []

        q_vec = self._embed([cleaned], query=True)
        scores, indices = self.index.search(q_vec, k)

        results: list[RetrievalResult] = []
        for score, idx in zip(scores[0], indices[0], strict=False):
            if idx < 0 or idx >= len(self.chunks):
                continue
            results.append(RetrievalResult(chunk=self.chunks[idx], score=float(score)))

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def save(self, directory: str | Path) -> None:
        """Serialize index and chunk metadata to disk."""
        target_dir = Path(directory)
        target_dir.mkdir(parents=True, exist_ok=True)

        # 1. Chunks metadata
        chunks_file = target_dir / "chunks.json"
        chunks_payload = [c.model_dump() for c in self.chunks]
        chunks_file.write_text(
            json.dumps(chunks_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # 2. Pipeline metadata
        meta = {
            "embedding_dim": self.embedding_dim,
            "backend": "faiss" if self._is_faiss else "numpy",
            "num_chunks": len(self.chunks),
        }
        (target_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        # 3. Vector Index
        if self._is_faiss and faiss is not None:
            faiss.write_index(self.index, str(target_dir / "index.faiss"))
            # Also save vectors.npy as universal fallback
            if hasattr(self.index, "reconstruct_n"):
                try:
                    vecs = self.index.reconstruct_n(0, self.index.ntotal)
                    np.save(target_dir / "vectors.npy", vecs)
                except Exception as exc:  # pragma: no cover
                    logger.debug("Could not reconstruct FAISS vectors for numpy backup: %s", exc)
        else:
            np.save(target_dir / "vectors.npy", self.index.vectors)

    def load(self, directory: str | Path) -> None:
        """Deserialize index and chunk metadata from disk."""
        target_dir = Path(directory)
        if not target_dir.exists():
            raise FileNotFoundError(f"Directory not found: {target_dir}")

        chunks_file = target_dir / "chunks.json"
        meta_file = target_dir / "meta.json"

        if not chunks_file.exists() or not meta_file.exists():
            raise FileNotFoundError(f"Missing metadata in {target_dir}")

        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        self.embedding_dim = int(meta.get("embedding_dim", self.embedding_dim))

        chunks_data = json.loads(chunks_file.read_text(encoding="utf-8"))
        self.chunks = [DocumentChunk.model_validate(c) for c in chunks_data]

        faiss_file = target_dir / "index.faiss"
        numpy_file = target_dir / "vectors.npy"

        if not self._force_numpy and _FAISS_AVAILABLE and faiss is not None and faiss_file.exists():
            self.index = faiss.read_index(str(faiss_file))
            self._is_faiss = True
        elif numpy_file.exists():
            vectors = np.load(numpy_file)
            if not self._force_numpy and _FAISS_AVAILABLE and faiss is not None:
                self.index = faiss.IndexFlatIP(self.embedding_dim)
                if len(vectors) > 0:
                    self.index.add(np.ascontiguousarray(vectors, dtype=np.float32))
                self._is_faiss = True
            else:
                self.index = _NumpyVectorStore(self.embedding_dim)
                self.index.add(vectors)
                self._is_faiss = False
        else:
            raise FileNotFoundError(f"No index file found in {target_dir}")

    def __len__(self) -> int:
        return len(self.chunks)
