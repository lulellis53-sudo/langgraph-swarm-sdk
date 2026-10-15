"""SQLite document store: the pipeline's "put in db" stage."""

from __future__ import annotations

import hashlib
import heapq
import json
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

from WebSearch.backend.docs import ExtractedDoc

if TYPE_CHECKING:
    from WebSearch.backend.semantic import Embedder

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    url        TEXT PRIMARY KEY,
    text       TEXT NOT NULL,
    digest     TEXT NOT NULL,
    chars      INTEGER NOT NULL,
    fetched_at REAL NOT NULL
)
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open (and initialize) the documents database at *path*."""
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def doc_digest(doc: ExtractedDoc) -> str:
    """Content digest used for store-level dedupe (matches dedupe_docs)."""
    return hashlib.blake2b(doc.text.casefold().encode(), digest_size=16).hexdigest()


def put_documents(conn: sqlite3.Connection, docs: Iterable[ExtractedDoc]) -> int:
    """Insert docs, skipping URLs and digests already stored; return rows added."""
    added = 0
    now = time.time()
    for doc in docs:
        cur = conn.execute(
            "INSERT OR IGNORE INTO documents(url, text, digest, chars, fetched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (doc.url, doc.text, doc_digest(doc), len(doc.text), now),
        )
        added += cur.rowcount
    conn.commit()
    return added


def count_documents(conn: sqlite3.Connection) -> int:
    """Total stored documents."""
    row = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
    return int(row[0]) if row else 0


def semantic_search(
    conn: sqlite3.Connection,
    docs: Iterable[ExtractedDoc],
    query: str,
    *,
    embedder: Embedder,
    top_k: int = 10,
) -> list[tuple[ExtractedDoc, float]]:
    """Index documents in SQLite's vector extension and return nearest query matches.

    When sqlite-vec cannot load, vectors stay in SQLite as float32 blobs and NumPy
    computes cosine top-k in bounded database batches. Vector rows are reused by URL
    and updated when the stored content changes.
    """
    import numpy as np

    if not query.strip():
        raise ValueError("query must not be empty")
    if top_k < 1:
        return []
    batch = list(docs)
    dim = int(getattr(embedder, "dim", 0))
    if dim < 1:
        raise ValueError("embedder must expose a positive dim")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS semantic_index_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    row = conn.execute("SELECT value FROM semantic_index_meta WHERE key='dim'").fetchone()
    if row is not None and int(row[0]) != dim:
        raise ValueError(f"semantic index dimension is {row[0]}, embedder dimension is {dim}")
    embedder_id = f"{type(embedder).__qualname__}:{getattr(embedder, 'model_name', '')}"
    model_row = conn.execute(
        "SELECT value FROM semantic_index_meta WHERE key='embedder'"
    ).fetchone()
    if model_row is not None and model_row[0] != embedder_id:
        raise ValueError("semantic index embedder changed; use a new database path to reindex")

    sqlite_vec = _load_sqlite_vec(conn)
    existing_vector_table = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='semantic_vectors'"
    ).fetchone()
    if existing_vector_table is not None:
        is_virtual = str(existing_vector_table[0]).upper().startswith("CREATE VIRTUAL TABLE")
        if is_virtual and not sqlite_vec:
            raise RuntimeError(
                "semantic_vectors uses sqlite-vec, but this SQLite build cannot load it"
            )
        if not is_virtual:
            sqlite_vec = False
    conn.execute(
        "INSERT OR IGNORE INTO semantic_index_meta(key, value) VALUES ('dim', ?)", (str(dim),)
    )
    conn.execute(
        "INSERT OR IGNORE INTO semantic_index_meta(key, value) VALUES ('embedder', ?)",
        (embedder_id,),
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS semantic_documents (
               rowid INTEGER PRIMARY KEY, url TEXT NOT NULL UNIQUE, text TEXT NOT NULL,
               digest TEXT NOT NULL
           )"""
    )
    if sqlite_vec:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS semantic_vectors "
            f"USING vec0(embedding float[{dim}])"
        )
    else:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS semantic_vectors (
                   rowid INTEGER PRIMARY KEY, embedding BLOB NOT NULL
               )"""
        )

    pending: list[tuple[ExtractedDoc, str, int | None]] = []
    for doc in batch:
        digest = doc_digest(doc)
        existing = conn.execute(
            "SELECT rowid, digest FROM semantic_documents WHERE url=?", (doc.url,)
        ).fetchone()
        if existing and existing[1] == digest:
            continue
        rowid = int(existing[0]) if existing else None
        pending.append((doc, digest, rowid))

    raw_vectors = embedder.embed([doc.text for doc, _, _ in pending]) if pending else []
    vectors = _unit_rows(raw_vectors) if pending else np.empty((0, dim), dtype=np.float32)
    if len(vectors) != len(pending) or vectors.shape[1] != dim:
        raise ValueError("embedder returned vectors with an unexpected shape")
    for (doc, digest, old_id), vector in zip(pending, vectors, strict=True):
        if old_id is not None:
            conn.execute("DELETE FROM semantic_vectors WHERE rowid=?", (old_id,))
            conn.execute(
                "UPDATE semantic_documents SET text=?, digest=? WHERE rowid=?",
                (doc.text, digest, old_id),
            )
            rowid = old_id
        else:
            cursor = conn.execute(
                "INSERT INTO semantic_documents(url, text, digest) VALUES (?, ?, ?)",
                (doc.url, doc.text, digest),
            )
            new_id = cursor.lastrowid
            if new_id is None:
                raise RuntimeError("SQLite did not return an id for an indexed document")
            rowid = int(new_id)
        if sqlite_vec:
            conn.execute(
                "INSERT INTO semantic_vectors(rowid, embedding) VALUES (?, vec_f32(?))",
                (rowid, json.dumps(vector.tolist())),
            )
        else:
            conn.execute(
                "INSERT INTO semantic_vectors(rowid, embedding) VALUES (?, ?)",
                (rowid, np.asarray(vector, dtype=np.float32).tobytes()),
            )

    query_vector = _unit_rows(embedder.embed([query], query=True))[0]
    if sqlite_vec:
        rows = conn.execute(
            """SELECT d.rowid, d.url, d.text, v.distance
               FROM semantic_vectors AS v
               JOIN semantic_documents AS d ON d.rowid=v.rowid
               WHERE v.embedding MATCH vec_f32(?) AND k=?
               ORDER BY v.distance""",
            (json.dumps(query_vector.tolist()), top_k),
        ).fetchall()
        scored = [
            (int(rowid), str(url), str(text), 1.0 / (1.0 + float(distance)))
            for rowid, url, text, distance in rows
        ]
    else:
        cursor = conn.execute(
            """SELECT d.rowid, d.url, d.text, v.embedding
               FROM semantic_vectors AS v
               JOIN semantic_documents AS d ON d.rowid=v.rowid"""
        )
        best: list[tuple[float, int, str, str]] = []
        while rows := cursor.fetchmany(256):
            matrix = np.stack([np.frombuffer(row[3], dtype=np.float32) for row in rows])
            scores = matrix @ query_vector
            for row, score in zip(rows, scores, strict=True):
                candidate = (float(score), -int(row[0]), str(row[1]), str(row[2]))
                if len(best) < top_k:
                    heapq.heappush(best, candidate)
                elif candidate[:2] > best[0][:2]:
                    heapq.heapreplace(best, candidate)
        scored = [(-rowid, url, text, score) for score, rowid, url, text in best]
        scored.sort(key=lambda item: (-item[3], item[0]))

    by_url = {doc.url: doc for doc in batch}
    results: list[tuple[ExtractedDoc, float]] = []
    for _, url, text, score in scored:
        doc = by_url.get(url, ExtractedDoc(url, text, "sqlite-vector-index", len(text)))
        results.append((doc, score))
    conn.commit()
    return results


def _unit_rows(vectors: Any) -> np.ndarray:
    """Validate and L2-normalize a matrix of embedding rows."""
    import numpy as np

    rows = np.asarray(vectors, dtype=np.float32)
    if rows.ndim == 1:
        rows = rows.reshape(1, -1)
    if rows.ndim != 2:
        raise ValueError("embedder must return a 2D vector matrix")
    norms = np.linalg.norm(rows, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return np.ascontiguousarray(rows / norms, dtype=np.float32)


def _load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """Load sqlite-vec when the local SQLite build supports loadable extensions."""
    try:
        conn.execute("SELECT vec_version()").fetchone()
        return True
    except sqlite3.Error:
        pass
    enable_extension = getattr(conn, "enable_load_extension", None)
    if not callable(enable_extension):
        return _reject_unavailable_vector_table(conn)
    try:
        import sqlite_vec

        enable_extension(True)
        sqlite_vec.load(conn)
        return True
    except ImportError, AttributeError, sqlite3.Error:
        return _reject_unavailable_vector_table(conn)
    finally:
        enable_extension(False)


def _reject_unavailable_vector_table(conn: sqlite3.Connection) -> bool:
    """Refuse to misread an existing sqlite-vec virtual table as a blob table."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name='semantic_vectors'").fetchone()
    if row and str(row[0]).upper().startswith("CREATE VIRTUAL TABLE"):
        raise RuntimeError("semantic_vectors uses sqlite-vec, but this SQLite build cannot load it")
    return False
