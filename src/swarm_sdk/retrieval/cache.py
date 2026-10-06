"""Exact and semantic response cache."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
import time

import numpy as np

from swarm_sdk.compute import batch_cosine
from swarm_sdk.memory.opencl_store import OpenClVecStore
from swarm_sdk.retrieval.embeddings import Embedder, unit

_SPACE = re.compile(r"\s+")
_INDEX_ROWS = 256


def normalize(text: str) -> str:
    return _SPACE.sub(" ", text.strip().lower())


class SemanticCache:
    def __init__(
        self,
        path: str,
        embedder: Embedder,
        threshold: float = 0.97,
        *,
        ttl_days: int | None = None,
        use_index: bool = False,
    ) -> None:
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
        for table in ("exact_cache", "semantic_cache"):
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
            stored = self._conn.execute("SELECT vector, response FROM semantic_cache").fetchall()
        if not stored:
            return None

        candidates: list[np.ndarray] = []
        responses: list[str] = []
        for blob, response in stored:
            other = np.frombuffer(blob, dtype=np.float32)
            if other.shape == vector.shape:
                candidates.append(other)
                responses.append(str(response))
        if not candidates:
            return None

        scores = batch_cosine(vector, np.stack(candidates))
        best_idx = int(scores.argmax())
        if float(scores[best_idx]) >= self.threshold:
            return responses[best_idx]
        return None

    def store(self, text: str, response: str) -> None:
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
