"""Exact and semantic response cache."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading

import numpy as np

from swarm_sdk.embeddings import Embedder, unit
from swarm_sdk.gpu import batch_cosine

_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _SPACE.sub(" ", text.strip().lower())


class SemanticCache:
    def __init__(self, path: str, embedder: Embedder, threshold: float = 0.97) -> None:
        self.embedder = embedder
        self.threshold = threshold
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
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
        self._conn.commit()

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
            self._conn.execute(
                "INSERT OR REPLACE INTO exact_cache(key, response) VALUES (?, ?)",
                (key, response),
            )
            self._conn.execute(
                "INSERT INTO semantic_cache(vector, response) VALUES (?, ?)",
                (blob, response),
            )
            self._conn.commit()
