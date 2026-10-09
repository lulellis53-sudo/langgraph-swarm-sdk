"""``websearch --prompt``: all providers, dork, routing and forecast."""

from __future__ import annotations

import io
import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Never

import numpy as np
import pytest
from WebSearch.backend.docs import ExtractedDoc
from WebSearch.backend.route import RouteError, dedupe_normalize, route, semantic_handler
from WebSearch.backend.semantic import default_embedder, summarize_score
from WebSearch.backend.store import connect, count_documents, semantic_search
from WebSearch.cli import build_parser, build_query, main
from WebSearch.forecast import ForecastUnavailable, forecast_hits, record_run
from WebSearch.frontend.websearchers import SearcherSpec, SearchFn, SearchHit, load_providers

PAGE = (
    "<html><body><h1>Forecasting with LightGBM</h1>"
    "<p>LightGBM builds gradient boosted trees for time series forecasting tasks. "
    "Cats are unrelated animals that sleep most of the day in warm places.</p></body></html>"
)


def _backend(prefix: str, urls: list[str]) -> SearchFn:
    def search(query: str, spec: SearcherSpec) -> list[SearchHit]:
        seen.setdefault(spec.id, []).append(query)
        return [
            SearchHit(f"{prefix} {u}", u, f"snippet about {u} long enough text", spec.id)
            for u in urls
        ]

    return search


seen: dict[str, list[str]] = {}


@pytest.fixture(autouse=True)
def _reset() -> None:
    seen.clear()


def _backends() -> dict[str, SearchFn]:
    ids = [s.id for s in load_providers().searchers]
    return {sid: _backend(sid, [f"https://{sid}.example/{i}" for i in range(2)]) for sid in ids}


def test_one_prompt_reaches_every_provider() -> None:
    out = io.StringIO()
    backends = _backends()
    code = main(
        ["--prompt", "lightgbm forecast", "--json", "--limit", "0"], backends=backends, out=out
    )
    assert code == 0
    assert set(seen) == set(backends)
    assert all(queries == ["lightgbm forecast"] for queries in seen.values())
    assert json.loads(out.getvalue())["hits"]


def test_dork_flags_build_google_dork_query() -> None:
    args = build_parser().parse_args(
        [
            "--prompt",
            "lightgbm forecast",
            "--site",
            "github.com",
            "--filetype",
            "pdf",
            "--exclude",
            "jobs",
            "--after",
            "2026-01-01",
        ]
    )
    assert build_query(args) == (
        "(lightgbm) AND (forecast) site:github.com filetype:pdf -jobs after:2026-01-01"
    )


def test_prompt_without_operators_is_sent_verbatim() -> None:
    args = build_parser().parse_args(["--prompt", 'exact "phrase" here'])
    assert build_query(args) == 'exact "phrase" here'


def test_bad_dork_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--prompt", "x", "--site", "a b"], backends={}) == 2
    assert "site" in capsys.readouterr().err


def test_unknown_route_exits_2_before_searching(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--prompt", "x", "--route", "nosql"], backends=_backends()) == 2
    assert not seen
    assert "nosql" in capsys.readouterr().err


def test_route_sql_and_semantic_end_to_end(tmp_path: Path) -> None:
    db = tmp_path / "docs.db"
    out = io.StringIO()
    code = main(
        ["--prompt", "lightgbm forecasting", "--json", "--route", "sql,semantic", "--db", str(db)],
        backends={"ddg": _backend("ddg", ["https://a.example/1", "https://b.example/2"])},
        fetch=lambda url: PAGE.encode(),
        out=out,
    )
    report = json.loads(out.getvalue())
    assert code == 0
    by_target = {r["target"]: r for r in report["routes"]}
    assert by_target["sql"]["detail"]["stored"] == 1  # identical pages dedupe to one doc
    assert report["docs"] == 1
    top = by_target["semantic"]["detail"]["summaries"][0]
    assert "LightGBM" in top["summary"]
    conn = connect(db)
    assert count_documents(conn) == 1
    assert conn.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0] == 1


def test_route_isolates_a_failing_path() -> None:
    doc = ExtractedDoc("https://a.example", "Some text that is long enough to keep.", "x", 10)

    def boom(_docs: Sequence[ExtractedDoc]) -> Never:
        raise sqlite3.OperationalError("disk full")

    clean, results = route(
        [doc],
        ["sql", "semantic", "sql"],
        {"sql": boom, "semantic": semantic_handler("text keep")},
    )
    assert [r.target for r in results] == ["sql", "semantic"]
    assert not results[0].ok and "disk full" in results[0].error
    assert results[1].ok and len(clean) == 1


def test_route_rejects_unknown_target_without_running() -> None:
    with pytest.raises(RouteError, match="nosql"):
        route([], ["nosql"], {})


def test_dedupe_normalize_cleans_and_dedupes() -> None:
    docs = [
        ExtractedDoc("u1", "Hello​   World", "x", 5),
        ExtractedDoc("u2", "hello world", "x", 5),
        ExtractedDoc("u3", "   ", "x", 3),
    ]
    clean = dedupe_normalize(docs)
    assert [d.url for d in clean] == ["u1"]
    assert clean[0].text == "Hello World"


def test_summarize_score_ranks_relevant_doc_first() -> None:
    docs = [
        ExtractedDoc("cats", "Cats sleep all day long in the warm sun by the window.", "x", 1),
        ExtractedDoc(
            "lgbm", "LightGBM trains gradient boosted trees for forecasting time series.", "x", 1
        ),
    ]
    ranked = summarize_score(docs, "lightgbm gradient boosted forecasting")
    assert [r.url for r in ranked] == ["lgbm", "cats"]
    assert ranked[0].score > ranked[1].score


def test_summarize_score_rejects_empty_query() -> None:
    with pytest.raises(ValueError, match="query"):
        summarize_score([], "  ")


def test_default_embedder_prefers_fastembed_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.machinery
    import importlib.util

    monkeypatch.delenv("WEBSEARCH_EMBED_BACKEND", raising=False)
    monkeypatch.delenv("WEBSEARCH_EMBED_MODEL", raising=False)
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: importlib.machinery.ModuleSpec(name, loader=None),
    )
    assert type(default_embedder()).__name__ == "FastEmbedder"


def test_default_embedder_uses_offline_fallback_without_fastembed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util

    monkeypatch.delenv("WEBSEARCH_EMBED_BACKEND", raising=False)
    monkeypatch.delenv("WEBSEARCH_EMBED_MODEL", raising=False)
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    assert type(default_embedder()).__name__ == "LexicalEmbedder"


class _VectorEmbedder:
    dim = 3

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        del query
        vectors = {"alpha": [1.0, 0.0, 0.0], "beta": [0.0, 1.0, 0.0], "q": [1, 0, 0]}
        return np.asarray([vectors[text] for text in texts], dtype=np.float32)


def test_semantic_search_indexes_and_reuses_vectors(tmp_path: Path) -> None:
    db = tmp_path / "vectors.db"
    docs = [
        ExtractedDoc("https://a.example", "alpha", "x", 5),
        ExtractedDoc("https://b.example", "beta", "x", 4),
    ]
    conn = connect(db)
    matches = semantic_search(conn, docs, "q", embedder=_VectorEmbedder(), top_k=1)
    assert [(doc.url, score) for doc, score in matches] == [(docs[0].url, pytest.approx(1.0))]
    conn.close()

    conn = connect(db)
    matches = semantic_search(conn, docs, "q", embedder=_VectorEmbedder(), top_k=2)
    assert [doc.url for doc, _score in matches] == [docs[0].url, docs[1].url]
    assert conn.execute("SELECT COUNT(*) FROM semantic_documents").fetchone()[0] == 2
    conn.close()


class _FakeEngine:
    last: Any

    def fit(self, df: Any) -> _FakeEngine:
        self.last = df
        return self

    def predict(self, horizon: int) -> Any:
        import pandas as pd  # ty: ignore[unresolved-import]

        ds = pd.date_range(self.last["ds"].max() + pd.Timedelta(days=1), periods=horizon, freq="D")
        return pd.DataFrame({"unique_id": "q", "ds": ds, "lgbm": [-1.0] + [5.0] * (horizon - 1)})


def test_forecast_uses_recorded_daily_history() -> None:
    pytest.importorskip("pandas")
    conn = sqlite3.connect(":memory:")
    hit = SearchHit("t", "https://a.example", "s", "ddg")
    for day in range(15):
        record_run(conn, "q", [hit] * (day % 3 + 1), at=1_790_000_000 + day * 86_400)
    days = forecast_hits(conn, "q", horizon=3, engine_factory=_FakeEngine)
    assert len(days) == 3
    assert days[0][1] == 0.0  # negative prediction clipped
    assert days[1][1] == 5.0


def test_forecast_needs_history() -> None:
    pytest.importorskip("pandas")
    conn = sqlite3.connect(":memory:")
    record_run(conn, "q", [], at=1_790_000_000)
    with pytest.raises(ForecastUnavailable, match="history"):
        forecast_hits(conn, "q", engine_factory=_FakeEngine)


def test_cli_forecast_reports_unavailable_not_crash(tmp_path: Path) -> None:
    out = io.StringIO()
    code = main(
        ["--prompt", "x", "--forecast", "--json", "--db", str(tmp_path / "d.db")],
        backends={"ddg": _backend("ddg", ["https://a.example/1"])},
        out=out,
    )
    assert code == 0
    assert "forecast_error" in json.loads(out.getvalue())


@pytest.mark.parametrize(
    "flags",
    [["--after", "2026-13-01"], ["--after", "2026-06-02", "--before", "2026-06-01"]],
)
def test_bad_or_inverted_dates_exit_2(flags: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--prompt", "x", *flags], backends=_backends()) == 2
    assert not seen  # rejected before any provider was called
    assert capsys.readouterr().err.startswith("websearch:")


def test_after_and_before_appear_in_the_query_sent_to_providers() -> None:
    out = io.StringIO()
    main(
        ["--prompt", "lightgbm", "--after", "2026-06-01", "--before", "2026-07-01", "--json"],
        backends=_backends(),
        out=out,
    )
    expected = "(lightgbm) after:2026-06-01 before:2026-07-01"
    assert json.loads(out.getvalue())["query"] == expected
    assert all(queries == [expected] for queries in seen.values())


def test_report_flag_lists_every_provider_with_status() -> None:
    out = io.StringIO()
    main(
        ["--prompt", "x", "--json", "--report"],
        backends={"ddg": _backend("ddg", ["https://a.example/1"])},
        out=out,
    )
    data = json.loads(out.getvalue())
    status = {p["id"]: p["status"] for p in data["providers"]}
    assert status["ddg"] == "ok" and status["tavily"] == "no_backend"
    assert data["merge"]["final"] == len(data["hits"]) == 1
