"""SQLite store: the only interface between pipeline stages."""

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Self

from technews.models import Article
from technews.text import canonical_url, content_hash

_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    published TEXT,
    excerpt TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    tags TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published);
CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
"""

_TAG_SEP = "\x1f"


class Store:
    """Deduplicating article store backed by one SQLite file."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.executescript(_SCHEMA)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the connection."""
        self._conn.close()

    def add(self, article: Article) -> bool:
        """Insert ``article``; return False when its URL or content already exists."""
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO articles "
            "(url, source, category, title, published, excerpt, content_hash, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                canonical_url(article.url),
                article.source,
                article.category,
                article.title,
                article.published,
                article.excerpt,
                content_hash(article.title, article.excerpt),
                _TAG_SEP.join(article.tags),
            ),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def add_many(self, articles: Iterable[Article]) -> int:
        """Insert each article; return how many were new."""
        return sum(1 for article in articles if self.add(article))

    def count(self) -> int:
        """Return the number of stored articles."""
        return self._conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]

    def recent(self, limit: int = 50, category: str | None = None) -> list[Article]:
        """Return articles newest first (undated last), optionally for one category."""
        sql = "SELECT url, source, category, title, published, excerpt, tags FROM articles"
        args: list[object] = []
        if category is not None:
            sql += " WHERE category = ?"
            args.append(category)
        sql += " ORDER BY published IS NULL, published DESC, id DESC LIMIT ?"
        args.append(limit)
        rows = self._conn.execute(sql, args).fetchall()
        return [
            Article(
                url=url,
                source=source,
                category=cat,
                title=title,
                published=published,
                excerpt=excerpt,
                tags=tuple(t for t in tags.split(_TAG_SEP) if t),
            )
            for url, source, cat, title, published, excerpt, tags in rows
        ]
