"""Daily news digest into SQLite, weekend ingest into the vector store.

``daily`` searches each topic (all providers), scrapes the hits, dedupes/normalizes,
scores every page against the topic prompt and stores it once per ``(topic, url)``.
``weekly`` runs only on Saturday/Sunday (or ``--force``): it embeds the week's
not-yet-ingested documents above ``min_score`` into the vector store, marks them
ingested and writes a row to the ``signals`` table (the ingest signal).

    python -m WebSearch.digest daily
    python -m WebSearch.digest weekly
    python -m WebSearch.digest status
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from WebSearch.agent_tools import search_hits
from WebSearch.backend import extract_and_normalize
from WebSearch.backend.route import dedupe_normalize
from WebSearch.backend.semantic import summarize_score
from WebSearch.frontend.websearchers import SearchFn, load_providers
from WebSearch.midend import FetchFn, crawl_then_scrape

if TYPE_CHECKING:
    from swarm_sdk.memory.base import MemoryStore
    from swarm_sdk.retrieval.embeddings import Embedder

logger = logging.getLogger(__name__)

DEFAULT_DB = "websearch_daily.db"
DEFAULT_TOPICS: dict[str, str] = {
    "trending": "top trending news today",
    "tech": "best technology news today",
    "games": "video game news today",
}
_MAX_TEXT_CHARS = 20_000
_WEEKEND = (5, 6)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_docs (
    id          INTEGER PRIMARY KEY,
    day         TEXT NOT NULL,
    topic       TEXT NOT NULL,
    url         TEXT NOT NULL,
    title       TEXT NOT NULL,
    summary     TEXT NOT NULL,
    text        TEXT NOT NULL,
    score       REAL NOT NULL,
    ingested_at REAL,
    UNIQUE (topic, url)
);
CREATE TABLE IF NOT EXISTS daily_runs (
    id     INTEGER PRIMARY KEY,
    day    TEXT NOT NULL,
    topic  TEXT NOT NULL,
    hits   INTEGER NOT NULL,
    docs   INTEGER NOT NULL,
    stored INTEGER NOT NULL,
    ran_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
    id     INTEGER PRIMARY KEY,
    ts     REAL NOT NULL,
    kind   TEXT NOT NULL,
    week   TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the digest database, creating tables on first use."""
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    return conn


def _query_for(base: str, day: date) -> str:
    return f"{base} {day.strftime('%B')} {day.day} {day.year}"


def daily(
    conn: sqlite3.Connection,
    *,
    day: date | None = None,
    topics: Mapping[str, str] | None = None,
    limit: int = 8,
    backends: Mapping[str, SearchFn] | None = None,
    fetch: FetchFn | None = None,
    timeout_s: float = 45.0,
) -> list[dict[str, Any]]:
    """Collect every topic for ``day`` and store new documents.

    A document already stored for the same topic (any earlier day) is skipped, so a
    story that stays on the front page is kept once.

    Returns:
        One summary per topic: ``topic``, ``query``, ``hits``, ``docs``, ``stored``.
    """
    today = day or date.today()
    cfg = load_providers()
    report: list[dict[str, Any]] = []
    for topic, base in (topics or DEFAULT_TOPICS).items():
        query = _query_for(base, today)
        hits = search_hits(query, limit=limit, config=cfg, backends=backends, timeout_s=timeout_s)
        titles = {hit.url: hit.title for hit in hits}
        pages = crawl_then_scrape(hits, fetch=fetch, config=cfg)
        docs = dedupe_normalize(
            [
                extract_and_normalize(p.html, url=p.url, config=cfg, main_first=True)
                for p in pages
                if p.html
            ]
        )
        scored = {s.url: s for s in summarize_score(docs, base)} if docs else {}
        stored = 0
        for doc in docs:
            item = scored.get(doc.url)
            if item is None:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO daily_docs"
                "(day, topic, url, title, summary, text, score) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    today.isoformat(),
                    topic,
                    doc.url,
                    titles.get(doc.url, doc.url),
                    item.summary,
                    doc.text[:_MAX_TEXT_CHARS],
                    item.score,
                ),
            )
            stored += cur.rowcount
        conn.execute(
            "INSERT INTO daily_runs(day, topic, hits, docs, stored, ran_at) VALUES (?,?,?,?,?,?)",
            (today.isoformat(), topic, len(hits), len(docs), stored, time.time()),
        )
        conn.commit()
        report.append(
            {"topic": topic, "query": query, "hits": len(hits), "docs": len(docs), "stored": stored}
        )
    return report


def _signal(conn: sqlite3.Connection, kind: str, week: str, detail: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO signals(ts, kind, week, detail) VALUES (?, ?, ?, ?)",
        (time.time(), kind, week, json.dumps(detail, sort_keys=True)),
    )
    conn.commit()


def weekly(
    conn: sqlite3.Connection,
    *,
    store: MemoryStore,
    embedder: Embedder,
    today: date | None = None,
    min_score: float = 0.15,
    force: bool = False,
    batch_size: int = 32,
) -> dict[str, Any]:
    """Ingest the last 7 days of un-ingested documents into the vector store.

    Skips (and signals ``weekly_skipped``) on a weekday unless ``force``. On success
    writes a ``weekly_ingest`` signal; if the store fails midway the rows added so
    far stay marked and a ``weekly_partial`` signal records it.

    Returns:
        ``status`` (``ingested``, ``noop`` when nothing qualified, ``partial`` or ``skipped``)
        plus counts.
    """
    now = today or date.today()
    iso = now.isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    if not force and now.weekday() not in _WEEKEND:
        result: dict[str, Any] = {"status": "skipped", "reason": "not weekend", "week": week}
        _signal(conn, "weekly_skipped", week, result)
        return result

    since = (now - timedelta(days=6)).isoformat()
    rows = conn.execute(
        "SELECT id, day, topic, url, title, summary FROM daily_docs "
        "WHERE ingested_at IS NULL AND day >= ? AND score >= ? ORDER BY day, id",
        (since, min_score),
    ).fetchall()
    low = conn.execute(
        "SELECT COUNT(*) FROM daily_docs WHERE ingested_at IS NULL AND day >= ? AND score < ?",
        (since, min_score),
    ).fetchone()[0]

    by_topic: dict[str, int] = {}
    ingested = 0
    failed = ""
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        texts = [f"{r[2]} | {r[1]} | {r[4]}\n{r[3]}\n{r[5]}" for r in chunk]
        try:
            vectors = embedder.embed(texts)
            for row, text, vector in zip(chunk, texts, vectors, strict=True):
                store.add(text, vector)
                conn.execute(
                    "UPDATE daily_docs SET ingested_at = ? WHERE id = ?", (time.time(), row[0])
                )
                by_topic[row[2]] = by_topic.get(row[2], 0) + 1
                ingested += 1
            conn.commit()
        except (OSError, ValueError, sqlite3.Error) as exc:
            conn.commit()
            failed = type(exc).__name__
            logger.warning("weekly ingest stopped: %s", failed)
            break
    status = "partial" if failed else ("ingested" if ingested else "noop")
    result = {
        "status": status,
        "week": week,
        "ingested": ingested,
        "below_min_score": low,
        "by_topic": by_topic,
        **({"error": failed} if failed else {}),
    }
    kind = {"partial": "weekly_partial", "ingested": "weekly_ingest", "noop": "weekly_noop"}[status]
    _signal(conn, kind, week, result)
    return result


def status(conn: sqlite3.Connection) -> dict[str, Any]:
    """Counts per topic and the latest signals."""
    topics = {
        topic: {"docs": docs, "ingested": ingested or 0}
        for topic, docs, ingested in conn.execute(
            "SELECT topic, COUNT(*), SUM(ingested_at IS NOT NULL) FROM daily_docs GROUP BY topic"
        )
    }
    signals = [
        {"ts": ts, "kind": kind, "week": week, "detail": json.loads(detail)}
        for ts, kind, week, detail in conn.execute(
            "SELECT ts, kind, week, detail FROM signals ORDER BY id DESC LIMIT 5"
        )
    ]
    return {"topics": topics, "signals": signals}


def _parse_topics(raw: Sequence[str]) -> dict[str, str]:
    topics: dict[str, str] = {}
    for item in raw:
        name, sep, query = item.partition("=")
        if not sep or not name.strip() or not query.strip():
            raise ValueError(f"--topic needs name=query, got {item!r}")
        topics[name.strip()] = query.strip()
    return topics


def main(
    argv: Sequence[str] | None = None,
    *,
    backends: Mapping[str, SearchFn] | None = None,
    fetch: FetchFn | None = None,
    store: MemoryStore | None = None,
    embedder: Embedder | None = None,
    today: date | None = None,
    out: Any = None,
) -> int:
    """CLI entry point: ``daily``, ``weekly`` or ``status``. Returns the exit code."""
    parser = argparse.ArgumentParser(prog="python -m WebSearch.digest", description=__doc__)
    parser.add_argument("command", choices=("daily", "weekly", "status"))
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--topic", action="append", default=[], metavar="NAME=QUERY")
    parser.add_argument("--min-score", type=float, default=0.15)
    parser.add_argument("--force", action="store_true", help="run weekly on a weekday")
    parser.add_argument("--today", metavar="YYYY-MM-DD", help="act as if this were today")
    args = parser.parse_args(argv)
    stream = out or sys.stdout
    if args.today and today is None:
        try:
            today = date.fromisoformat(args.today)
        except ValueError:
            print(f"digest: --today is not a real date: {args.today!r}", file=sys.stderr)
            return 2
    conn = connect(args.db)
    try:
        if args.command == "daily":
            try:
                topics = _parse_topics(args.topic) or None
            except ValueError as exc:
                print(f"digest: {exc}", file=sys.stderr)
                return 2
            result: Any = daily(
                conn, day=today, topics=topics, limit=args.limit, backends=backends, fetch=fetch
            )
        elif args.command == "weekly":
            if store is None or embedder is None:
                from swarm_sdk.config.settings import load_merged_settings
                from swarm_sdk.core.swarm import default_embedder, open_store

                settings, _ = load_merged_settings()
                store = store or open_store(settings)
                embedder = embedder or default_embedder(settings)
            result = weekly(
                conn,
                store=store,
                embedder=embedder,
                today=today,
                min_score=args.min_score,
                force=args.force,
            )
        else:
            result = status(conn)
        print(json.dumps(result, indent=2, ensure_ascii=False), file=stream)
        return 1 if isinstance(result, dict) and result.get("status") == "partial" else 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
