"""Feature database: daily per-category article counts for trend prediction."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Self

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT NOT NULL,
    category TEXT NOT NULL,
    n INTEGER NOT NULL,
    PRIMARY KEY(date, category)
);
"""

@dataclass(frozen=True, slots=True)
class DailyCount:
    """One (date, category) aggregate row."""

    date: str
    category: str
    n: int


class FeatureStore:
    """SQLite-backed daily counts used as prediction features."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def ensure_schema(self) -> None:
        """Create ``daily_stats`` if absent."""
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        """Close the connection."""
        self._conn.close()

    def upsert_daily(self, date: str, category: str, n: int) -> None:
        """Insert or replace one (date, category) count row."""
        self._conn.execute(
            "INSERT INTO daily_stats(date, category, n) VALUES (?, ?, ?) "
            "ON CONFLICT(date, category) DO UPDATE SET n = excluded.n",
            (date, category, n),
        )
        self._conn.commit()

    def daily_counts(self, category: str | None = None) -> list[DailyCount]:
        """Return all rows ordered by (category, date); filter by category when given."""
        sql = "SELECT date, category, n FROM daily_stats"
        args: list[object] = []
        if category is not None:
            sql += " WHERE category = ?"
            args.append(category)
        sql += " ORDER BY category ASC, date ASC"
        rows = self._conn.execute(sql, args).fetchall()
        return [DailyCount(date=d, category=c, n=n) for d, c, n in rows]

    def categories(self) -> list[str]:
        """Return distinct categories sorted alphabetically."""
        rows = self._conn.execute(
            "SELECT DISTINCT category FROM daily_stats ORDER BY category ASC"
        ).fetchall()
        return [row[0] for row in rows]

    def backfill_from_articles(self, article_db: str | Path) -> int:
        """Recompute daily_stats from the articles DB; return rows written.

        Articles with NULL ``published`` are skipped.
        """
        self.ensure_schema()
        with sqlite3.connect(Path(article_db)) as conn:
            rows = conn.execute(
                "SELECT substr(published, 1, 10), category, COUNT(*) "
                "FROM articles WHERE published IS NOT NULL "
                "GROUP BY substr(published, 1, 10), category"
            ).fetchall()
        self._conn.executemany(
            "INSERT INTO daily_stats(date, category, n) VALUES (?, ?, ?) "
            "ON CONFLICT(date, category) DO UPDATE SET n = excluded.n",
            rows,
        )
        self._conn.commit()
        return len(rows)
