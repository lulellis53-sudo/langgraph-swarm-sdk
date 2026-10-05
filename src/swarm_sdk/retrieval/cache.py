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
from swarm_sdk.retrieval.redis_exact import RedisExactCache

_SPACE = re.compile(r"\s+")
_INDEX_ROWS = 256
_QUERY_EMBEDDING_ROWS = 256
_DEFAULT_SEMANTIC_ROWS = 10_000


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
        redis_url: str | None = None,
        redis_ttl_s: int = 86400,
        max_entries: int = 10000,
        max_semantic_rows: int = _DEFAULT_SEMANTIC_ROWS,
    ) -> None:
        """Open (or create) the cache database with exact + semantic layers."""
        self.embedder = embedder
        self.threshold = threshold
        self.ttl_days = ttl_days
        self.use_index = use_index
        self.max_entries = max(max_entries, 1)
        if max_semantic_rows < 1:
            raise ValueError("max_semantic_rows must be at least 1")
        self.max_semantic_rows = max_semantic_rows
        self._redis_cache = (
            RedisExactCache(redis_url, "swarm:response", redis_ttl_s) if redis_url else None
        )
        self._lock = threading.Lock()
        self._embedding_lock = threading.Lock()
        self._query_embeddings: OrderedDict[str, np.ndarray] = OrderedDict()
        self._semantic_matrix: np.ndarray | None = None
        self._semantic_rows: list[tuple[int, str]] = []
        self._semantic_data_version = -1
        self._semantic_write_version = 0
        self._semantic_matrix_write_version = -1
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS exact_cache (
                key TEXT PRIMARY KEY,
                response TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                inserted_at REAL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS semantic_cache (
                id INTEGER PRIMARY KEY,
                query_text TEXT NOT NULL,
                vector BLOB NOT NULL,
                response TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                inserted_at REAL,
                accessed_at REAL
            )
            """
        )
        ttl_purged = 0
        for table in ("exact_cache", "semantic_cache"):
            columns = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            if "inserted_at" not in columns:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN inserted_at REAL")
            if "tenant_id" not in columns:
                self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"
                )
        semantic_columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(semantic_cache)")
        }
        if "accessed_at" not in semantic_columns:
            self._conn.execute("ALTER TABLE semantic_cache ADD COLUMN accessed_at REAL")
        if "query_text" not in semantic_columns:
            self._conn.execute("ALTER TABLE semantic_cache ADD COLUMN query_text TEXT")
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
        self._lru_purged = 0

    def _warm_index(self) -> OpenClVecStore:
        """Load the newest default-tenant rows into an in-memory index."""
        index = OpenClVecStore(self.embedder.dim, max_vectors=_INDEX_ROWS)
        rows = self._conn.execute(
            """
            SELECT vector, response FROM semantic_cache
            WHERE tenant_id = 'default'
            ORDER BY id DESC LIMIT ?
            """,
            (_INDEX_ROWS,),
        ).fetchall()
        for blob, response in reversed(rows):
            vector = _decode_vector(blob, self.embedder.dim)
            if vector is not None:
                index.add(str(response), vector)
        return index

    def _touch_semantic(self, query_text: str, tenant_id: str) -> None:
        """Update accessed_at for the semantic row matching this query, if any."""
        normalized = normalize(query_text)
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id FROM semantic_cache
                WHERE tenant_id = ? AND query_text = ?
                ORDER BY id DESC LIMIT 1
                """,
                (tenant_id, normalized),
            ).fetchone()
            if row is not None:
                self._conn.execute(
                    "UPDATE semantic_cache SET accessed_at = ? WHERE id = ?",
                    (time.time(), row[0]),
                )
                self._conn.commit()

    def _candidate_matrix(self, tenant_id: str) -> tuple[np.ndarray, list[tuple[int, str]]]:
        """Load and cache normalized semantic vectors for one tenant."""
        with self._lock:
            data_version = int(self._conn.execute("PRAGMA data_version").fetchone()[0])
            if (
                tenant_id == "default"
                and self._semantic_matrix is not None
                and data_version == self._semantic_data_version
                and self._semantic_write_version == self._semantic_matrix_write_version
            ):
                return self._semantic_matrix, self._semantic_rows
            stored = self._conn.execute(
                """
                SELECT id, vector, response FROM (
                    SELECT id, vector, response
                    FROM semantic_cache
                    WHERE tenant_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) ORDER BY id ASC
                """,
                (tenant_id, self.max_semantic_rows),
            ).fetchall()
        vectors: list[np.ndarray] = []
        rows: list[tuple[int, str]] = []
        for row_id, blob, response in stored:
            vector = _decode_vector(blob, self.embedder.dim)
            if vector is not None:
                vectors.append(vector)
                rows.append((int(row_id), str(response)))
        matrix = np.stack(vectors) if vectors else np.empty((0, self.embedder.dim), dtype="<f4")
        matrix.setflags(write=False)
        if tenant_id == "default":
            with self._lock:
                self._semantic_matrix = matrix
                self._semantic_rows = rows
                self._semantic_data_version = int(
                    self._conn.execute("PRAGMA data_version").fetchone()[0]
                )
                self._semantic_matrix_write_version = self._semantic_write_version
        return matrix, rows

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

    def _evict_if_needed(self) -> None:
        """Enforce ``max_entries`` on the semantic cache, evicting LRU rows."""
        with self._lock:
            count_row = self._conn.execute(
                "SELECT COUNT(*) FROM semantic_cache WHERE tenant_id = 'default'"
            ).fetchone()
        count = int(count_row[0]) if count_row is not None else 0
        if count <= self.max_entries:
            return
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, query_text FROM semantic_cache
                WHERE tenant_id = 'default'
                ORDER BY accessed_at ASC NULLS FIRST, id ASC
                LIMIT ?
                """,
                (count - self.max_entries,),
            ).fetchall()
            if not rows:
                return
            ids = [row[0] for row in rows]
            keys = [
                hashlib.sha256(str(row[1]).encode()).hexdigest()
                for row in rows
                if row[1] is not None
            ]
            placeholders = ",".join("?" * len(ids))
            self._conn.execute(
                f"DELETE FROM semantic_cache WHERE id IN ({placeholders})",
                ids,
            )
            if keys:
                key_placeholders = ",".join("?" * len(keys))
                self._conn.execute(
                    f"DELETE FROM exact_cache WHERE key IN ({key_placeholders})",
                    keys,
                )
            self._lru_purged += len(ids)
            self._conn.commit()

    def lookup(self, text: str, *, tenant_id: str = "default") -> str | None:
        """Return the cached response for ``text`` or None (exact hit first)."""
        normalized = normalize(text)
        key = hashlib.sha256(normalized.encode()).hexdigest()
        if self._redis_cache is not None:
            response = self._redis_cache.get(f"{tenant_id}:{normalized}")
            if response is not None:
                self._exact_hits += 1
                return response
        with self._lock:
            row = self._conn.execute(
                "SELECT response FROM exact_cache WHERE key = ? AND tenant_id = ?",
                (key, tenant_id),
            ).fetchone()
        if row is not None:
            self._exact_hits += 1
            response = str(row[0])
            if self._redis_cache is not None:
                self._redis_cache.set(f"{tenant_id}:{normalized}", response)
            return response
        vector = self._query_vector(text)
        if self._index is not None and tenant_id == "default":
            hits = self._index.search(vector, 1)
            if hits and hits[0].score >= self.threshold:
                self._semantic_hits += 1
                # Best-effort LRU touch: update accessed_at for the newest matching row.
                with self._lock:
                    row = self._conn.execute(
                        """
                        SELECT id FROM semantic_cache
                        WHERE tenant_id = 'default' AND response = ?
                        ORDER BY id DESC LIMIT 1
                        """,
                        (hits[0].text,),
                    ).fetchone()
                    if row is not None:
                        self._conn.execute(
                            "UPDATE semantic_cache SET accessed_at = ? WHERE id = ?",
                            (time.time(), row[0]),
                        )
                        self._conn.commit()
                response = hits[0].text
                if self._redis_cache is not None:
                    self._redis_cache.set(f"{tenant_id}:{normalized}", response)
                return response
            self._misses += 1
            return None
        candidate_matrix, candidate_rows = self._candidate_matrix(tenant_id)
        if not candidate_rows:
            self._misses += 1
            return None
        scores = batch_cosine(vector, candidate_matrix)
        best_idx = int(scores.argmax())
        if float(scores[best_idx]) >= self.threshold:
            self._semantic_hits += 1
            row_id, response = candidate_rows[best_idx]
            with self._lock:
                self._conn.execute(
                    "UPDATE semantic_cache SET accessed_at = ? WHERE id = ?",
                    (time.time(), row_id),
                )
                self._conn.commit()
            if self._redis_cache is not None:
                self._redis_cache.set(f"{tenant_id}:{normalized}", response)
            return response
        self._misses += 1
        return None

    def stats(self) -> dict[str, int]:
        """Return cache counters since this instance was opened."""
        return {
            "exact_hits": self._exact_hits,
            "semantic_hits": self._semantic_hits,
            "misses": self._misses,
            "ttl_purged": self._ttl_purged,
            "lru_purged": self._lru_purged,
        }

    def lookup_batch(self, texts: list[str], *, tenant_id: str = "default") -> list[str | None]:
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
                    "SELECT response FROM exact_cache WHERE key = ? AND tenant_id = ?",
                    (key, tenant_id),
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

        if self._index is not None and tenant_id == "default":
            for offset, (i, _) in enumerate(pending):
                hits = self._index.search(query_vectors[offset], 1)
                if hits and hits[0].score >= self.threshold:
                    results[i] = hits[0].text
                    self._semantic_hits += 1
                else:
                    self._misses += 1
            return results

        candidate_matrix, candidate_rows = self._candidate_matrix(tenant_id)
        if not candidate_rows:
            self._misses += len(pending)
            return results
        # Both matrices are L2-normalized, so the matrix product is cosine similarity.
        scores = query_vectors @ candidate_matrix.T
        best_idx = scores.argmax(axis=1)
        best_scores = scores[np.arange(len(pending)), best_idx]
        now = time.time()
        with self._lock:
            for offset, (i, _) in enumerate(pending):
                if float(best_scores[offset]) >= self.threshold:
                    row_id, response = candidate_rows[int(best_idx[offset])]
                    results[i] = response
                    self._semantic_hits += 1
                    self._conn.execute(
                        "UPDATE semantic_cache SET accessed_at = ? WHERE id = ?",
                        (now, row_id),
                    )
                else:
                    self._misses += 1
            self._conn.commit()
        return results

    def store(self, text: str, response: str, *, tenant_id: str = "default") -> None:
        """Insert a response under both the exact key and its embedding."""
        normalized = normalize(text)
        key = hashlib.sha256(normalized.encode()).hexdigest()
        vector = self._query_vector(text)
        blob = _encode_vector(vector)
        with self._lock:
            now = time.time()
            self._conn.execute(
                """
                INSERT OR REPLACE INTO exact_cache(key, response, tenant_id, inserted_at)
                VALUES (?, ?, ?, ?)
                """,
                (key, response, tenant_id, now),
            )
            self._conn.execute(
                """
                INSERT INTO semantic_cache(
                    query_text, vector, response, tenant_id, inserted_at, accessed_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (normalized, blob, response, tenant_id, now, now),
            )
            self._conn.commit()
            self._semantic_write_version += 1
        if tenant_id == "default":
            self._evict_if_needed()
        if self._redis_cache is not None:
            self._redis_cache.set(f"{tenant_id}:{normalized}", response)
        if self._index is not None and tenant_id == "default":
            self._index.add(response, vector)


__all__ = ["SemanticCache", "normalize"]
