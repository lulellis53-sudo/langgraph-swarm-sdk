"""Daily digest into SQLite and weekend ingest into the vector store."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from WebSearch.backend.semantic import LexicalEmbedder
from WebSearch.digest import connect, daily, main, status, weekly
from WebSearch.frontend.websearchers import SearcherSpec, SearchFn, SearchHit

FRI = date(2026, 10, 2)
SAT = date(2026, 10, 3)
SNIP = "snippet long enough to survive the prefilter checks"

PAGES = {
    "https://n.example/gears": (
        "<html><body><h1>Gears launch</h1><p>Video game news: the new Gears title launches "
        "today with fresh features and a big patch for players.</p></body></html>"
    ),
    "https://n.example/chips": (
        "<html><body><h1>Chip</h1><p>Technology news: a company launches an AI chip into "
        "orbit to test hardware performance in space.</p></body></html>"
    ),
}


def _backend(*urls: str) -> SearchFn:
    def search(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [SearchHit(f"title {u[-5:]}", u, SNIP, spec.id) for u in urls]

    return search


def _run_daily(conn: sqlite3.Connection, day: date, *urls: str) -> list[dict]:
    return daily(
        conn,
        day=day,
        topics={"games": "video game news today", "tech": "technology news today"},
        backends={"ddg": _backend(*urls)},
        fetch=lambda url: PAGES[url].encode(),
    )


class _Store:
    def __init__(self, fail_after: int | None = None) -> None:
        self.rows: list[tuple[str, np.ndarray]] = []
        self.fail_after = fail_after

    def add(self, text: str, vector: np.ndarray) -> int:
        if self.fail_after is not None and len(self.rows) >= self.fail_after:
            raise OSError("disk full")
        self.rows.append((text, vector))
        return len(self.rows)

    def search(self, vector: np.ndarray, k: int) -> list:  # pragma: no cover - filler
        """Return no neighbours; only the ``add`` path is exercised here."""
        return []


def test_daily_stores_each_url_once_per_topic_across_days() -> None:
    conn = connect(":memory:")
    first = _run_daily(conn, FRI, "https://n.example/gears", "https://n.example/chips")
    assert [r["stored"] for r in first] == [2, 2]
    second = _run_daily(conn, SAT, "https://n.example/gears")  # story still on the front page
    assert [r["stored"] for r in second] == [0, 0]
    assert conn.execute("SELECT COUNT(*) FROM daily_docs").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM daily_runs").fetchone()[0] == 4
    assert first[0]["query"] == "video game news today October 2 2026"


def test_weekly_skips_and_signals_on_a_weekday() -> None:
    conn = connect(":memory:")
    _run_daily(conn, FRI, "https://n.example/gears")
    store = _Store()
    result = weekly(conn, store=store, embedder=LexicalEmbedder(64), today=date(2026, 10, 1))
    assert result["status"] == "skipped" and store.rows == []
    assert conn.execute("SELECT kind FROM signals").fetchall() == [("weekly_skipped",)]


def test_weekly_ingests_marks_and_signals_once() -> None:
    conn = connect(":memory:")
    _run_daily(conn, FRI, "https://n.example/gears", "https://n.example/chips")
    store = _Store()
    result = weekly(conn, store=store, embedder=LexicalEmbedder(64), today=SAT, min_score=-1.0)
    assert result["status"] == "ingested" and result["ingested"] == 4
    assert result["by_topic"] == {"games": 2, "tech": 2}
    assert len(store.rows) == 4
    assert "games | 2026-10-02" in store.rows[0][0]
    again = weekly(conn, store=store, embedder=LexicalEmbedder(64), today=SAT, min_score=-1.0)
    assert again["ingested"] == 0 and len(store.rows) == 4  # nothing re-ingested
    kinds = [k for (k,) in conn.execute("SELECT kind FROM signals ORDER BY id")]
    assert kinds == ["weekly_ingest", "weekly_noop"]
    assert again["status"] == "noop"
    assert result["week"] == "2026-W40"


def test_weekly_min_score_leaves_low_scores_unmarked() -> None:
    conn = connect(":memory:")
    _run_daily(conn, FRI, "https://n.example/gears")
    result = weekly(conn, store=_Store(), embedder=LexicalEmbedder(64), today=SAT, min_score=2.0)
    assert result["ingested"] == 0 and result["below_min_score"] == 2
    assert (
        conn.execute("SELECT COUNT(*) FROM daily_docs WHERE ingested_at IS NULL").fetchone()[0] == 2
    )


def test_weekly_store_failure_is_partial_and_keeps_progress() -> None:
    conn = connect(":memory:")
    _run_daily(conn, FRI, "https://n.example/gears", "https://n.example/chips")
    store = _Store(fail_after=1)
    result = weekly(conn, store=store, embedder=LexicalEmbedder(64), today=SAT, min_score=-1.0)
    assert result["status"] == "partial" and result["error"] == "OSError"
    assert result["ingested"] == 1
    marked = conn.execute("SELECT COUNT(*) FROM daily_docs WHERE ingested_at IS NOT NULL")
    assert marked.fetchone()[0] == 1
    assert status(conn)["signals"][0]["kind"] == "weekly_partial"
    retry = weekly(conn, store=_Store(), embedder=LexicalEmbedder(64), today=SAT, min_score=-1.0)
    assert retry["ingested"] == 3  # the rest, not the one already ingested


def test_weekly_force_runs_on_a_weekday() -> None:
    conn = connect(":memory:")
    _run_daily(conn, FRI, "https://n.example/gears")
    result = weekly(
        conn,
        store=_Store(),
        embedder=LexicalEmbedder(64),
        today=date(2026, 10, 1),
        force=True,
        min_score=-1.0,
    )
    assert result["status"] == "ingested" and result["ingested"] == 2


def test_cli_daily_weekly_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = str(tmp_path / "d.db")
    backends = {"ddg": _backend("https://n.example/gears")}

    def fetch(url: str) -> bytes:
        return PAGES[url].encode()

    assert (
        main(
            ["daily", "--db", db, "--topic", "games=video game news today"],
            backends=backends,
            fetch=fetch,
            today=FRI,
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)[0]["stored"] == 1
    store = _Store()
    assert (
        main(
            ["weekly", "--db", db, "--min-score", "-1"],
            store=store,
            embedder=LexicalEmbedder(64),
            today=SAT,
        )
        == 0
    )
    assert len(store.rows) == 1
    capsys.readouterr()
    assert main(["status", "--db", db]) == 0
    assert json.loads(capsys.readouterr().out)["topics"]["games"] == {"docs": 1, "ingested": 1}


def test_cli_rejects_malformed_topic(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["daily", "--db", ":memory:", "--topic", "nope"]) == 2
    assert "name=query" in capsys.readouterr().err
