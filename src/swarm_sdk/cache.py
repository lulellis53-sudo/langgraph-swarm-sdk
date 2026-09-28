"""Exact and semantic response cache."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from pathlib import Path

import numpy as np

from swarm_sdk.embeddings import Embedder, cosine, unit

_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _SPACE.sub(" ", text.strip().lower())


class SemanticCache:
    def __init__(self, path: str, embedder: Embedder, threshold: float = 0.97) -> None:
        self.embedder = embedder
        self.threshold = threshold
        self._lock = threading.Lock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
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
        best: str | None = None
        best_score = self.threshold
        with self._lock:
            stored = self._conn.execute("SELECT vector, response FROM semantic_cache").fetchall()
        for blob, response in stored:
            other = np.frombuffer(blob, dtype=np.float32)
            if other.shape != vector.shape:
                continue
            score = cosine(vector, other)
            if score >= best_score:
                best_score = score
                best = str(response)
        return best

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
