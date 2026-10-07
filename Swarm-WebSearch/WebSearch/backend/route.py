"""Dedupe + normalize documents, then fan them out to one or more target paths."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from WebSearch.backend.docs import ExtractedDoc, dedupe_docs
from WebSearch.backend.normalize import normalize_text
from WebSearch.backend.semantic import Embedder, default_embedder, summarize_score
from WebSearch.backend.store import connect, put_documents, semantic_search

type Handler = Callable[[Sequence[ExtractedDoc]], dict[str, Any]]

TARGETS = ("sql", "semantic")


class RouteError(ValueError):
    """Raised for an unknown route target or a missing handler."""


@dataclass(frozen=True, slots=True)
class RouteResult:
    """Outcome of one path; a failing path never stops the others.

    Attributes:
        target: Route name (``sql`` or ``semantic``).
        ok: ``False`` when the handler raised an expected I/O or value error.
        detail: Handler output (``stored`` for sql; ``summaries`` for semantic).
        error: Error text when ``ok`` is false.
    """

    target: str
    ok: bool
    detail: dict[str, Any] = field(default_factory=dict)
    error: str = ""


def dedupe_normalize(docs: Sequence[ExtractedDoc]) -> list[ExtractedDoc]:
    """Normalize every doc's text, then drop empty and content-duplicate docs."""
    return dedupe_docs(replace(doc, text=normalize_text(doc.text)) for doc in docs)


def sql_handler(db_path: str | Path) -> Handler:
    """Path ``sql``: INSERT OR IGNORE into the SQLite documents table (Persister)."""

    def handle(docs: Sequence[ExtractedDoc]) -> dict[str, Any]:
        conn = connect(db_path)
        try:
            return {"stored": put_documents(conn, docs), "db": str(db_path)}
        finally:
            conn.close()

    return handle


def semantic_handler(
    query: str,
    *,
    embedder: Embedder | None = None,
    db_path: str | Path = ":memory:",
) -> Handler:
    """Path ``semantic``: vector-search documents, then extract relevant summaries."""
    chosen_embedder = embedder if embedder is not None else default_embedder()

    def handle(docs: Sequence[ExtractedDoc]) -> dict[str, Any]:
        conn = connect(db_path)
        try:
            matches = semantic_search(
                conn, docs, query, embedder=chosen_embedder, top_k=max(len(docs), 1)
            )
        finally:
            conn.close()
        ranked_docs = [doc for doc, _score in matches]
        summaries = summarize_score(ranked_docs, query, embedder=chosen_embedder)
        vector_scores = {doc.url: score for doc, score in matches}
        return {
            "summaries": [
                {
                    "url": s.url,
                    "score": round(vector_scores.get(s.url, s.score), 4),
                    "summary": s.summary,
                }
                for s in sorted(
                    summaries, key=lambda summary: vector_scores.get(summary.url, summary.score),
                    reverse=True,
                )
            ],
            "embedding": type(chosen_embedder).__name__,
        }

    return handle


def route(
    docs: Sequence[ExtractedDoc],
    targets: Sequence[str],
    handlers: Mapping[str, Handler],
) -> tuple[list[ExtractedDoc], list[RouteResult]]:
    """Dedupe/normalize ``docs`` once, then run every requested path on the same docs.

    Args:
        docs: Extracted documents.
        targets: Any of :data:`TARGETS`; repeats are ignored, order is kept.
        handlers: Target name → handler.

    Returns:
        The clean docs and one :class:`RouteResult` per distinct target.

    Raises:
        RouteError: On an unknown target or a target without a handler (nothing runs).
    """
    wanted = list(dict.fromkeys(targets))
    for target in wanted:
        if target not in TARGETS:
            raise RouteError(f"unknown route {target!r}; choose from {TARGETS}")
        if target not in handlers:
            raise RouteError(f"no handler for route {target!r}")
    clean = dedupe_normalize(docs)
    results: list[RouteResult] = []
    for target in wanted:
        try:
            results.append(RouteResult(target, True, handlers[target](clean)))
        except (OSError, sqlite3.Error, ValueError, ImportError, RuntimeError) as exc:
            results.append(RouteResult(target, False, error=f"{type(exc).__name__}: {exc}"))
    return clean, results


__all__ = [
    "TARGETS",
    "Handler",
    "RouteError",
    "RouteResult",
    "dedupe_normalize",
    "route",
    "semantic_handler",
    "sql_handler",
]
