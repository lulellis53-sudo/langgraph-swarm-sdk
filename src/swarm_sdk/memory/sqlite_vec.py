"""sqlite-vec memory with int8 scalar quantization and FTS5 keyword index."""

from __future__ import annotations

import json
import sqlite3
import threading

import numpy as np

from swarm_sdk.gpu import topk_ip
from swarm_sdk.memory.base import MemoryHit
from swarm_sdk.retrieval.embeddings import unit
from swarm_sdk.retrieval.text import tokenize


def _fts_match_query(query: str) -> str:
    """Build an FTS5 MATCH string (AND of quoted tokens; avoids column syntax)."""
    terms = tokenize(query)
    if not terms:
        return '""'
    return " ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


class SqliteVecStore:
    def __init__(self, path: str, dim: int) -> None:
        self.dim = dim
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._sqlite_vec = False
        enable_extension = getattr(self._conn, "enable_load_extension", None)
        try:
            import sqlite_vec

            if callable(enable_extension):
                enable_extension(True)
                sqlite_vec.load(self._conn)
                enable_extension(False)
                self._conn.execute(
                    f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories USING vec0(
                        embedding int8[{dim}]
                    )
                    """
                )
                self._sqlite_vec = True
        except (ImportError, AttributeError, sqlite3.Error):
            # Some Python distributions compile SQLite without extension loading.
            # Keep persistence available with stdlib SQLite and stream INT8 vectors
            # through the same OpenCL/NumPy top-k dispatcher at query time.
            self._sqlite_vec = False
            if callable(enable_extension):
                enable_extension(False)
        if not self._sqlite_vec:
            legacy_table = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vec_memories'"
            ).fetchone()
            if legacy_table is not None:
                self._conn.close()
                raise RuntimeError(
                    "this database contains sqlite-vec storage, but this Python SQLite build "
                    "cannot load extensions; use an extension-enabled Python or a new database "
                    "path to avoid hiding existing vectors"
                )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_text (
                rowid INTEGER PRIMARY KEY,
                text TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                text
            )
            """
        )
        if not self._sqlite_vec:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_int8_vectors (
                    rowid INTEGER PRIMARY KEY,
                    embedding BLOB NOT NULL
                )
                """
            )
        self._conn.commit()
        self._next_id = int(
            self._conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM memory_text").fetchone()[0]
        )

    def add(self, text: str, vector: np.ndarray) -> int:
        normalized = unit(vector)
        if normalized.shape[0] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {normalized.shape[0]}")
        payload = json.dumps(normalized.tolist())
        quantized = np.rint(normalized * 127.0).clip(-127, 127).astype(np.int8)
        with self._lock:
            self._next_id += 1
            row_id = self._next_id
            if self._sqlite_vec:
                self._conn.execute(
                    """
                    INSERT INTO vec_memories(rowid, embedding)
                    VALUES (?, vec_quantize_int8(vec_f32(?), 'unit'))
                    """,
                    (row_id, payload),
                )
            else:
                self._conn.execute(
                    "INSERT INTO memory_int8_vectors(rowid, embedding) VALUES (?, ?)",
                    (row_id, quantized.tobytes()),
                )
            self._conn.execute(
                "INSERT INTO memory_text(rowid, text) VALUES (?, ?)",
                (row_id, text),
            )
            self._conn.execute(
                "INSERT INTO memory_fts(rowid, text) VALUES (?, ?)",
                (row_id, text),
            )
            self._conn.commit()
        return row_id

    def search(self, vector: np.ndarray, k: int) -> list[MemoryHit]:
        if k < 1:
            return []
        query = unit(vector)
        if query.shape[0] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {query.shape[0]}")
        if not self._sqlite_vec:
            return self._search_int8_batches(query, k)
        payload = json.dumps(query.tolist())
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT v.rowid, t.text, v.distance
                FROM vec_memories AS v
                JOIN memory_text AS t ON t.rowid = v.rowid
                WHERE v.embedding MATCH vec_quantize_int8(vec_f32(?), 'unit')
                  AND k = ?
                ORDER BY v.distance
                """,
                (payload, k),
            ).fetchall()
        hits: list[MemoryHit] = []
        for row_id, text, distance in rows:
            hits.append(
                MemoryHit(id=int(row_id), text=str(text), score=1.0 / (1.0 + float(distance)))
            )
        return hits

    def _search_int8_batches(self, query: np.ndarray, k: int) -> list[MemoryHit]:
        """Search persisted INT8 rows in bounded batches, optionally on OpenCL."""
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT v.rowid, v.embedding, t.text
                FROM memory_int8_vectors AS v
                JOIN memory_text AS t ON t.rowid = v.rowid
                ORDER BY v.rowid
                """
            )
            best: list[MemoryHit] = []
            while rows := cursor.fetchmany(256):
                vectors = [
                    np.frombuffer(blob, dtype=np.int8).astype(np.float32) / 127.0
                    for _, blob, _ in rows
                ]
                matrix = np.stack(vectors)
                indexes, scores = topk_ip(query, matrix, min(k, len(rows)))
                best.extend(
                    MemoryHit(
                        id=int(rows[int(index)][0]),
                        text=str(rows[int(index)][2]),
                        score=float(score),
                    )
                    for index, score in zip(indexes, scores, strict=True)
                )
                best.sort(key=lambda hit: hit.score, reverse=True)
                del best[k:]
            return best

    def keyword_search(self, query: str, k: int) -> list[MemoryHit]:
        if k < 1 or not query.strip():
            return []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT m.rowid, m.text, bm25(memory_fts) AS rank
                FROM memory_fts
                JOIN memory_text AS m ON m.rowid = memory_fts.rowid
                WHERE memory_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (_fts_match_query(query), k),
            ).fetchall()
        return [
            MemoryHit(id=int(row_id), text=str(text), score=abs(float(rank)))
            for row_id, text, rank in rows
        ]

    def close(self) -> None:
        self._conn.close()
