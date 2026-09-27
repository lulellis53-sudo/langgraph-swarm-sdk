"""sqlite-vec memory with int8 scalar quantization."""

from __future__ import annotations

import json
import sqlite3
import threading

import numpy as np

from swarm_sdk.embeddings import unit
from swarm_sdk.memory.base import MemoryHit


class SqliteVecStore:
    def __init__(self, path: str, dim: int) -> None:
        import sqlite_vec

        self.dim = dim
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories USING vec0(
                embedding int8[{dim}]
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_text (
                rowid INTEGER PRIMARY KEY,
                text TEXT NOT NULL
            )
            """
        )
        self._conn.commit()
        self._next_id = int(
            self._conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM memory_text").fetchone()[0]
        )

    def add(self, text: str, vector: np.ndarray) -> int:
        payload = json.dumps(unit(vector).tolist())
        with self._lock:
            self._next_id += 1
            row_id = self._next_id
            self._conn.execute(
                """
                INSERT INTO vec_memories(rowid, embedding)
                VALUES (?, vec_quantize_int8(vec_f32(?), 'unit'))
                """,
                (row_id, payload),
            )
            self._conn.execute(
                "INSERT INTO memory_text(rowid, text) VALUES (?, ?)",
                (row_id, text),
            )
            self._conn.commit()
        return row_id

    def search(self, vector: np.ndarray, k: int) -> list[MemoryHit]:
        if k < 1:
            return []
        payload = json.dumps(unit(vector).tolist())
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

    def close(self) -> None:
        self._conn.close()
