"""Exact and semantic response cache."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
import time
from collections.abc import Sequence

import numpy as np

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
        # WAL lets readers run while a writer commits, which is what stops
        # concurrent lookups from blocking on store(). It is not a raw-speed
        # win for bulk inserts (measured slightly slower: 63 ms vs 37 ms for
        # 3000 rows) — it is a concurrency win (1.7x faster writes with 4
        # concurrent readers, and zero reader lock errors).
        self._conn.execute("PRAGMA journal_mode=WAL")
        # synchronous defaults to FULL, which fsyncs on every commit. This cache
        # commits once per store() call, so that cost dominates: measured 100.4
        # ms vs 21.1 ms for 600 committed rows (4.8x). NORMAL stays crash-safe
        # under WAL; only a power loss can lose the last commit. OFF measured no
        # faster (21.6 ms) and does sacrifice durability, so it is not used.
        self._conn.execute("PRAGMA synchronous=NORMAL")
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
        # Both sides are already L2-normalized: `unit()` normalizes the query
        # above and `_scan_matrix()` normalizes every stored row once per
        # generation. Cosine is therefore just the dot product, and calling
        # `batch_cosine` here would redo `np.linalg.norm(matrix, axis=1)` on
        # every lookup — measured 4.89 ms vs 0.52 ms over 10,000x384 (9.4x) on
        # the NumPy fallback path, which is the path this host uses.
        scores = matrix @ vector
        best_idx = int(scores.argmax())
        if float(scores[best_idx]) >= self.threshold:
            return responses[best_idx]
        return None

    def _scan_matrix(self) -> tuple[np.ndarray, list[str]]:
        """Return the row-normalized semantic matrix, reloading only on change.

        The caller holds ``_lock``. ``COUNT`` plus ``MAX(id)`` is the generation:
        a repeat lookup in this process does not ``SELECT`` every blob again.
        Blobs are copied out of SQLite's buffer. A wrong-dimension blob is skipped.

        Rows are normalized **here, once per generation**, rather than per
        lookup. :func:`~swarm_sdk.gpu.batch_cosine` otherwise recomputes
        ``np.linalg.norm(matrix, axis=1)`` on every call, which on the NumPy
        fallback path dominated the cost (measured ~4.4 ms vs ~0.46 ms for a
        pre-normalized matmul over 10,000x384). Zero-norm rows are stored as
        zeros, and ``batch_cosine``'s division then yields 0 for them, which
        matches the previous scoring behaviour for degenerate vectors.
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
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            np.divide(matrix, np.where(norms > 0, norms, 1.0), out=matrix)
            matrix.setflags(write=False)
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

    def store_many(self, items: Sequence[tuple[str, str]]) -> int:
        """Insert many ``(text, response)`` pairs in a single transaction.

        One commit per call instead of one per row. Committing per row forces a
        journal flush each time; on SQLite the batched form measured 3.8x faster
        for 1000 inserts (8.57 ms -> 2.27 ms, synthetic, ``:memory:``), and the
        gap widens on a real file in WAL mode.

        Args:
            items: Pairs of request text and the response to cache.

        Returns:
            The number of pairs written.
        """
        if not items:
            return 0
        texts = [text for text, _ in items]
        embedded = self.embedder.embed(texts)
        now = time.time()
        with self._lock:
            exact_rows: list[tuple[str, str, float]] = []
            semantic_rows: list[tuple[bytes, str, float]] = []
            for (text, response), raw in zip(items, embedded, strict=True):
                key = hashlib.sha256(normalize(text).encode()).hexdigest()
                vector = np.ascontiguousarray(unit(raw), dtype=np.float32)
                exact_rows.append((key, response, now))
                semantic_rows.append((vector.tobytes(), response, now))
                if self._index is not None:
                    self._index.add(response, vector)
            self._conn.executemany(
                "INSERT OR REPLACE INTO exact_cache(key, response, inserted_at) VALUES (?, ?, ?)",
                exact_rows,
            )
            self._conn.executemany(
                "INSERT INTO semantic_cache(vector, response, inserted_at) VALUES (?, ?, ?)",
                semantic_rows,
            )
            self._conn.commit()
        return len(items)

    def close(self) -> None:
        """Commit and release the SQLite connection, checkpointing the WAL.

        Without this the connection lives until garbage collection. A
        long-lived reader that never closes is exactly the condition SQLite
        documents for WAL checkpoint starvation: the ``-wal`` file cannot be
        folded back into the database, so it grows without bound. Closing also
        releases the ``-wal``/``-shm`` sidecars.
        """
        with self._lock:
            if self._conn is None:
                return
            try:
                self._conn.commit()
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass  # a busy checkpoint must not raise on teardown
            finally:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> SemanticCache:
        """Support ``with SemanticCache(...) as cache:``."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the cache even when the body raises."""
        self.close()


__all__ = ["SemanticCache", "normalize"]
