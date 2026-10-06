"""Offline checks of the agentic WebSearch path, the prefilter report and the cowork pipeline."""

from __future__ import annotations

from pathlib import Path

from benchmark.Tasks.websearch_agentic.benchmark_websearch_agentic import run_agent
from benchmark.tests.fakes import Script, ScriptedModel, answer
from langchain_core.messages import AIMessage
from WebSearch.cowork_agents import run_cowork_pipeline
from WebSearch.frontend import SearcherSpec, SearchHit
from WebSearch.frontend.report import search_report

A = "https://a.example/lightgbm"
B = "https://b.example/forecast"
SNIPPET = "LightGBM gradient boosting for time series forecasting in practice."


def _backend(*rows: tuple[str, str, str], tokens: int = 0):
    def search(query: str, spec: SearcherSpec) -> list[SearchHit]:
        hits = [SearchHit(t, u, s, spec.id) for t, u, s in rows]
        if hits and tokens:
            hits[0] = SearchHit(hits[0].title, hits[0].url, hits[0].snippet, spec.id, tokens)
        return hits

    return search


def _tool_call(query: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "web_search_brief",
                "args": {"query": query},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )


def _final(text: str) -> AIMessage:
    usage = {"input_tokens": 40, "output_tokens": 10, "total_tokens": 50}
    return AIMessage(content=text, usage_metadata=usage)


BACKENDS = {
    "ddg": _backend(("LightGBM guide", A, SNIPPET)),
    "tavily": _backend(("Forecast intro", B, SNIPPET), ("LightGBM guide", A, SNIPPET)),
}


def test_agent_calls_search_tool_with_the_query_and_cites_only_hits() -> None:
    query = "(lightgbm) AND (forecasting) after:2026-06-01"
    model = ScriptedModel(script=Script([_tool_call(query), _final(f"Use LightGBM: {A}")]))
    run = run_agent(query, model, backends=BACKENDS)
    assert run.tool_calls == [("web_search_brief", {"query": query})]
    assert A in run.tool_urls and B in run.tool_urls
    assert run.grounded and run.ungrounded == []
    assert run.model_tokens == 65  # measured from the scripted usage metadata
    assert run.tool_tokens > 0


def test_agent_citing_an_unseen_url_is_flagged_as_ungrounded() -> None:
    fake = "https://invented.example/post"
    model = ScriptedModel(script=Script([_tool_call("q"), _final(f"See {A} and {fake}")]))
    run = run_agent("q", model, backends=BACKENDS)
    assert run.ungrounded == [fake]
    assert not run.grounded


def test_agent_answer_without_citation_is_not_grounded() -> None:
    model = ScriptedModel(script=Script([_tool_call("q"), _final("No links here.")]))
    assert not run_agent("q", model, backends=BACKENDS).grounded


def test_search_report_counts_prefilter_dedupe_and_failures() -> None:
    def boom(query: str, spec: SearcherSpec) -> list[SearchHit]:
        raise ValueError("secret-looking message must not leak")

    backends = {
        "ddg": _backend(
            ("LightGBM guide", A, SNIPPET),
            ("ftp page", "ftp://files.example/x", SNIPPET),
            ("", "https://untitled.example/", SNIPPET),
        ),
        "tavily": _backend(("LightGBM guide", A + "/", SNIPPET), tokens=7),
        "exa": boom,
    }
    report = search_report("q", backends=backends)
    rows = {p.id: p for p in report.providers}
    assert rows["ddg"].status == "ok"
    assert rows["ddg"].raw == 3 and rows["ddg"].kept == 1
    assert rows["ddg"].rejected == {"scheme": 1, "empty": 1}
    assert rows["tavily"].api_tokens == 7
    assert rows["exa"].status == "error" and rows["exa"].error == "ValueError"
    assert "secret" not in str(report.to_dict())
    assert rows["context7"].status == "no_backend"
    assert report.kept == 2 and report.exact_dupes == 1 and report.final == 1


def test_search_report_flags_missing_credentials(monkeypatch) -> None:
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.setattr("WebSearch.frontend.report.env_key", lambda spec: "")
    report = search_report("q", backends={"brave": _backend()}, searcher_id="brave")
    only = report.providers[0]
    assert (only.status, only.needs_credentials, only.credentials_set) == ("empty", True, False)


def test_cowork_pipeline_fetches_dedupes_and_stores(tmp_path: Path) -> None:
    html = b"<html><body><h1>Alpha</h1><p>Same body text here.</p></body></html>"
    pages = {"https://a.example/1": html, "https://b.example/2": html}
    report = run_cowork_pipeline(
        list(pages), fetch=lambda url: pages[url], db_path=tmp_path / "d.db"
    )
    assert report["fetched"] == 2 and report["docs"] == 1 and report["stored"] == 1


def test_scripted_final_answer_helper_is_plain_text() -> None:
    assert answer("x").content == "x"
