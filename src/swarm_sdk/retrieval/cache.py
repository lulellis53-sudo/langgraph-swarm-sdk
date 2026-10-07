"""Exact and semantic response cache."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
import time

import numpy as np

from swarm_sdk.gpu import batch_cosine
from swarm_sdk.memory.opencl_store import OpenClVecStore
from swarm_sdk.retrieval.embeddings import Embedder, unit

_SPACE = re.compile(r"\s+")
_INDEX_ROWS = 256


def normalize(text: str) -> str:
    """Lowercase and collapse whitespace: the cache's canonical text form."""
    return _SPACE.sub(" ", text.strip().lower())


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
        # SQLite cannot bind identifiers as parameters, so the interpolated
        # table names are pinned to this whitelist (Mimosa: SQL injection).
        known_tables = ("exact_cache", "semantic_cache")
        for table in known_tables:
            if table not in known_tables or ";" in table:
                raise ValueError(f"unexpected table name: {table!r}")
            columns = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            if "inserted_at" not in columns:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN inserted_at REAL")
        if ttl_days is not None:
            cutoff = time.time() - ttl_days * 86400
            for table in ("exact_cache", "semantic_cache"):
                self._conn.execute(
                    f"DELETE FROM {table} WHERE inserted_at IS NOT NULL AND inserted_at < ?",
                    (cutoff,),
                )
        self._conn.commit()
        self._index = self._warm_index() if use_index else None
        self._scan_generation: tuple[int, int] | None = None
        self._scan_vectors: np.ndarray | None = None
        self._scan_responses: list[str] = []

    def _warm_index(self) -> OpenClVecStore:
        """Load the newest rows into an in-memory index (older rows stay in SQLite)."""
        index = OpenClVecStore(self.embedder.dim, max_vectors=_INDEX_ROWS)
        rows = self._conn.execute(
            "SELECT vector, response FROM semantic_cache ORDER BY id DESC LIMIT ?",
            (_INDEX_ROWS,),
        ).fetchall()
        for blob, response in reversed(rows):
            if len(blob) == self.embedder.dim * 4:
                index.add(str(response), np.frombuffer(blob, dtype=np.float32))
        return index

    def lookup(self, text: str) -> str | None:
        """Return the cached response for ``text`` or None (exact hit first)."""
        key = hashlib.sha256(normalize(text).encode()).hexdigest()
        with self._lock:
            row = self._conn.execute(
                "SELECT response FROM exact_cache WHERE key = ?",
                (key,),
            ).fetchone()
        if row is not None:
            return str(row[0])
        vector = unit(self.embedder.embed([text])[0])
        if self._index is not None:
            hits = self._index.search(vector, 1)
            if hits and hits[0].score >= self.threshold:
                return hits[0].text
            return None
        with self._lock:
            matrix, responses = self._scan_matrix()
        if matrix.shape[0] == 0:
            return None
        scores = batch_cosine(vector, matrix)
        best_idx = int(scores.argmax())
        if float(scores[best_idx]) >= self.threshold:
            return responses[best_idx]
        return None

    def _scan_matrix(self) -> tuple[np.ndarray, list[str]]:
        """Return the contiguous semantic matrix, reloading only when rows change.

        The caller holds ``_lock``. ``COUNT`` plus ``MAX(id)`` is the generation:
        a repeat lookup in this process does not ``SELECT`` every blob again.
        Blobs are copied out of SQLite's buffer. A wrong-dimension blob is skipped.
        """
        row = self._conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM semantic_cache"
        ).fetchone()
        generation = (int(row[0]), int(row[1])) if row is not None else (0, 0)
        if self._scan_generation == generation and self._scan_vectors is not None:
            return self._scan_vectors, self._scan_responses
        stored = self._conn.execute("SELECT vector, response FROM semantic_cache").fetchall()
        dim = self.embedder.dim
        vectors: list[np.ndarray] = []
        responses: list[str] = []
        for blob, response in stored:
            other = np.frombuffer(blob, dtype=np.float32)
            if other.shape == (dim,):
                vectors.append(other)
                responses.append(str(response))
        if not vectors:
            matrix = np.empty((0, dim), dtype=np.float32)
        else:
            # Preallocate the result matrix and copy each vector exactly once.
            matrix = np.empty((len(vectors), dim), dtype=np.float32)
            for i, vector in enumerate(vectors):
                matrix[i] = vector
            matrix = np.ascontiguousarray(matrix)
        self._scan_vectors = matrix
        self._scan_responses = responses
        self._scan_generation = generation
        return matrix, responses

    def store(self, text: str, response: str) -> None:
        """Insert a response under both the exact key and its embedding."""
        key = hashlib.sha256(normalize(text).encode()).hexdigest()
        vector = np.ascontiguousarray(unit(self.embedder.embed([text])[0]), dtype=np.float32)
        blob = vector.tobytes()
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
