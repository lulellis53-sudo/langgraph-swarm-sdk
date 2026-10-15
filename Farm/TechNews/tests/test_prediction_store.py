"""Offline tests for technews.prediction.store.FeatureStore."""

import sqlite3

from technews.prediction.store import DailyCount, FeatureStore


def make_articles_db(path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE articles (
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
        """
    )
    rows = [
        ("u1", "s", "ai", "t1", "2026-10-01T10:00:00+00:00", "e", "h1"),
        ("u2", "s", "ai", "t2", "2026-10-01T12:00:00+00:00", "e", "h2"),
        ("u3", "s", "web", "t3", "2026-10-02T09:00:00+00:00", "e", "h3"),
        ("u4", "s", "ai", "t4", None, "e", "h4"),  # NULL published: skipped
    ]
    conn.executemany(
        "INSERT INTO articles(url, source, category, title, published, excerpt, "
        "content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_schema_idempotent(tmp_path):
    db = tmp_path / "features.db"
    with FeatureStore(db) as fs:
        fs.ensure_schema()
        fs.ensure_schema()  # second call is a no-op
        fs.upsert_daily("2026-10-01", "ai", 2)
    with FeatureStore(db) as fs:
        fs.ensure_schema()
        assert fs.daily_counts() == [DailyCount("2026-10-01", "ai", 2)]


def test_upsert_overwrites(tmp_path):
    with FeatureStore(tmp_path / "f.db") as fs:
        fs.ensure_schema()
        fs.upsert_daily("2026-10-01", "ai", 2)
        fs.upsert_daily("2026-10-01", "ai", 5)
        assert fs.daily_counts() == [DailyCount("2026-10-01", "ai", 5)]


def test_daily_counts_filter_and_order(tmp_path):
    with FeatureStore(tmp_path / "f.db") as fs:
        fs.ensure_schema()
        fs.upsert_daily("2026-10-02", "web", 1)
        fs.upsert_daily("2026-10-01", "web", 3)
        fs.upsert_daily("2026-10-01", "ai", 2)
        assert fs.daily_counts() == [
            DailyCount("2026-10-01", "ai", 2),
            DailyCount("2026-10-01", "web", 3),
            DailyCount("2026-10-02", "web", 1),
        ]
        assert fs.daily_counts(category="web") == [
            DailyCount("2026-10-01", "web", 3),
            DailyCount("2026-10-02", "web", 1),
        ]
        assert fs.daily_counts(category="nope") == []


def test_categories(tmp_path):
    with FeatureStore(tmp_path / "f.db") as fs:
        fs.ensure_schema()
        assert fs.categories() == []
        fs.upsert_daily("2026-10-01", "web", 1)
        fs.upsert_daily("2026-10-01", "ai", 2)
        assert fs.categories() == ["ai", "web"]


def test_backfill_from_articles(tmp_path):
    articles_db = tmp_path / "articles.db"
    make_articles_db(articles_db)
    with FeatureStore(tmp_path / "f.db") as fs:
        assert fs.backfill_from_articles(articles_db) == 2
        assert fs.daily_counts() == [
            DailyCount("2026-10-01", "ai", 2),
            DailyCount("2026-10-02", "web", 1),
        ]
        assert fs.categories() == ["ai", "web"]
        assert fs.backfill_from_articles(articles_db) == 2  # grouped rows, not articles
        assert fs.daily_counts(category="ai") == [DailyCount("2026-10-01", "ai", 2)]
