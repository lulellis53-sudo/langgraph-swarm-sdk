"""Exact and semantic response cache."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
import time
from collections import OrderedDict

import numpy as np

from swarm_sdk.gpu import batch_cosine
from swarm_sdk.memory.opencl_store import OpenClVecStore
from swarm_sdk.retrieval.embeddings import Embedder, unit

_SPACE = re.compile(r"\s+")
_INDEX_ROWS = 256
_QUERY_EMBEDDING_ROWS = 256


def normalize(text: str) -> str:
    """Lowercase and collapse whitespace: the cache's canonical text form."""
    return _SPACE.sub(" ", text.strip().lower())


def _encode_vector(vector: np.ndarray) -> bytes:
    """Serialize an embedding as contiguous little-endian float32 values."""
    return np.ascontiguousarray(vector, dtype="<f4").tobytes()


def _decode_vector(blob: bytes, dimension: int) -> np.ndarray | None:
    """Deserialize a vector blob when its byte length matches ``dimension``."""
    if len(blob) != dimension * np.dtype("<f4").itemsize:
        return None
    return np.frombuffer(blob, dtype="<f4")


class SemanticCache:
    """Response cache with an exact SHA-256 layer and a cosine semantic layer."""

    def __init__(
        self,
        path: str,
        embedder: Embedder,
        threshold: float = 0.97,
        *,
        ttl_days: int | None = None,
        use_index: bool = False,
    ) -> None:
        """Open (or create) the cache database with exact + semantic layers."""
        self.embedder = embedder
        self.threshold = threshold
        self.ttl_days = ttl_days
        self.use_index = use_index
        self._lock = threading.Lock()
        self._embedding_lock = threading.Lock()
        self._query_embeddings: OrderedDict[str, np.ndarray] = OrderedDict()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS exact_cache (
                key TEXT PRIMARY KEY,
                response TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS semantic_cache (
                id INTEGER PRIMARY KEY,
                vector BLOB NOT NULL,
                response TEXT NOT NULL
            )
            """
        )
        ttl_purged = 0
        for table in ("exact_cache", "semantic_cache"):
            columns = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            if "inserted_at" not in columns:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN inserted_at REAL")
        if ttl_days is not None:
            cutoff = time.time() - ttl_days * 86400
            for table in ("exact_cache", "semantic_cache"):
                cursor = self._conn.execute(
                    f"DELETE FROM {table} WHERE inserted_at IS NOT NULL AND inserted_at < ?",
                    (cutoff,),
                )
                ttl_purged += cursor.rowcount
        self._conn.commit()
        self._index = self._warm_index() if use_index else None
        self._exact_hits = 0
        self._semantic_hits = 0
        self._misses = 0
        self._ttl_purged = ttl_purged

    def _warm_index(self) -> OpenClVecStore:
        """Load the newest rows into an in-memory index (older rows stay in SQLite)."""
        index = OpenClVecStore(self.embedder.dim, max_vectors=_INDEX_ROWS)
        rows = self._conn.execute(
            "SELECT vector, response FROM semantic_cache ORDER BY id DESC LIMIT ?",
            (_INDEX_ROWS,),
        ).fetchall()
        for blob, response in reversed(rows):
            vector = _decode_vector(blob, self.embedder.dim)
            if vector is not None:
                index.add(str(response), vector)
        return index

    def _query_vector(self, text: str) -> np.ndarray:
        """Return a normalized query embedding, reusing a bounded in-memory cache."""
        with self._embedding_lock:
            vector = self._query_embeddings.get(text)
            if vector is not None:
                self._query_embeddings.move_to_end(text)
                return vector

        vector = np.ascontiguousarray(unit(self.embedder.embed([text])[0]), dtype="<f4")
        vector.setflags(write=False)
        with self._embedding_lock:
            existing = self._query_embeddings.get(text)
            if existing is not None:
                self._query_embeddings.move_to_end(text)
                return existing
            self._query_embeddings[text] = vector
            if len(self._query_embeddings) > _QUERY_EMBEDDING_ROWS:
                self._query_embeddings.popitem(last=False)
        return vector

    def lookup(self, text: str) -> str | None:
        """Return the cached response for ``text`` or None (exact hit first)."""
        key = hashlib.sha256(normalize(text).encode()).hexdigest()
        with self._lock:
            row = self._conn.execute(
                "SELECT response FROM exact_cache WHERE key = ?",
                (key,),
            ).fetchone()
        if row is not None:
            self._exact_hits += 1
            return str(row[0])
        vector = self._query_vector(text)
        if self._index is not None:
            hits = self._index.search(vector, 1)
            if hits and hits[0].score >= self.threshold:
                self._semantic_hits += 1
                return hits[0].text
            self._misses += 1
            return None
        with self._lock:
            stored = self._conn.execute("SELECT vector, response FROM semantic_cache").fetchall()
        if not stored:
            self._misses += 1
            return None

        candidates: list[np.ndarray] = []
        responses: list[str] = []
        for blob, response in stored:
            other = _decode_vector(blob, self.embedder.dim)
            if other is not None:
                candidates.append(other)
                responses.append(str(response))
        if not candidates:
            self._misses += 1
            return None

        scores = batch_cosine(vector, np.stack(candidates))
        best_idx = int(scores.argmax())
        if float(scores[best_idx]) >= self.threshold:
            self._semantic_hits += 1
            return responses[best_idx]
        self._misses += 1
        return None

    def stats(self) -> dict[str, int]:
        """Return cache counters since this instance was opened."""
        return {
            "exact_hits": self._exact_hits,
            "semantic_hits": self._semantic_hits,
            "misses": self._misses,
            "ttl_purged": self._ttl_purged,
        }

    def lookup_batch(self, texts: list[str]) -> list[str | None]:
        """Lookup many queries in one batch, amortizing embedding cost.

        Exact hits are resolved first; remaining queries are embedded once and
        scored against the semantic layer in a single matrix operation.
        """
        results: list[str | None] = [None] * len(texts)
        pending: list[tuple[int, str]] = []
        for i, text in enumerate(texts):
            key = hashlib.sha256(normalize(text).encode()).hexdigest()
            with self._lock:
                row = self._conn.execute(
                    "SELECT response FROM exact_cache WHERE key = ?", (key,)
                ).fetchone()
            if row is not None:
                results[i] = str(row[0])
                self._exact_hits += 1
            else:
                pending.append((i, text))

        if not pending:
            return results

        # Embed all remaining queries together.
        query_texts = [text for _, text in pending]
        query_vectors = self.embedder.embed(query_texts)
        query_vectors = np.ascontiguousarray(query_vectors, dtype="<f4")
        query_vectors /= np.linalg.norm(query_vectors, axis=1, keepdims=True) + 1e-12
        query_vectors.setflags(write=False)

        if self._index is not None:
            for offset, (i, _) in enumerate(pending):
                hits = self._index.search(query_vectors[offset], 1)
                if hits and hits[0].score >= self.threshold:
                    results[i] = hits[0].text
                    self._semantic_hits += 1
                else:
                    self._misses += 1
            return results

        with self._lock:
            stored = self._conn.execute("SELECT vector, response FROM semantic_cache").fetchall()
        if not stored:
            self._misses += len(pending)
            return results

        candidates: list[np.ndarray] = []
        responses: list[str] = []
        for blob, response in stored:
            other = _decode_vector(blob, self.embedder.dim)
            if other is not None:
                candidates.append(other)
                responses.append(str(response))
        if not candidates:
            self._misses += len(pending)
            return results

        candidate_matrix = np.stack(candidates)
        # Both matrices are L2-normalized, so the matrix product is cosine similarity.
        scores = query_vectors @ candidate_matrix.T
        best_idx = scores.argmax(axis=1)
        best_scores = scores[np.arange(len(pending)), best_idx]
        for offset, (i, _) in enumerate(pending):
            if float(best_scores[offset]) >= self.threshold:
                results[i] = responses[int(best_idx[offset])]
                self._semantic_hits += 1
            else:
                self._misses += 1
        return results

    def store(self, text: str, response: str) -> None:
        """Insert a response under both the exact key and its embedding."""
        key = hashlib.sha256(normalize(text).encode()).hexdigest()
        vector = self._query_vector(text)
        blob = _encode_vector(vector)
        with self._lock:
            now = time.time()
            self._conn.execute(
                "INSERT OR REPLACE INTO exact_cache(key, response, inserted_at) VALUES (?, ?, ?)",
                (key, response, now),
            )
            self._conn.execute(
                "INSERT INTO semantic_cache(vector, response, inserted_at) VALUES (?, ?, ?)",
                (blob, response, now),
            )
            self._conn.commit()
        if self._index is not None:
            self._index.add(response, vector)


__all__ = ["SemanticCache", "normalize"]
