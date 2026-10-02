"""SQLite document store: the pipeline's "put in db" stage."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path

from WebSearch.backend.docs import ExtractedDoc

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
