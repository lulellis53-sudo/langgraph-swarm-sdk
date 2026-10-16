"""Offline tests for the SearXNG searcher (Vane-compatible JSON API).

Fake HTTP via a monkeypatched ``call_json``; no network, no running instance.
One optional live smoke test runs only when ``SEARXNG_URL`` is set.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from WebSearch.frontend import providers as providers_mod
from WebSearch.frontend.fanout import builtin_searchers, search
from WebSearch.frontend.registry import load_providers
from WebSearch.frontend.types import ProvidersConfig, SearcherSpec

_VANE_PAYLOAD = {
    "query": "langgraph",
    "number_of_results": 3,
    "results": [
        {
            "title": "LangGraph",
            "url": "https://www.langchain.com/langgraph",
            "content": "Low-level orchestration framework for multi-agent systems.",
            "engine": "duckduckgo",
        },
        {
            "title": "SearXNG docs",
            "url": "https://docs.searxng.org/",
            "content": "Privacy-respecting metasearch engine.",
            "engine": "bing",
        },
        {"title": "bad scheme", "url": "ftp://example.org/x", "content": "skip me"},
        "not-a-dict",
    ],
}


def _spec(**kwargs: object) -> SearcherSpec:
    """Build the searxng searcher spec as declared in providers.yaml."""
    return SearcherSpec(
        id="searxng",
        kind="websearcher",
        base_url_env="SEARXNG_URL",
        engine="duckduckgo,bing",
        **kwargs,  # ty: ignore[unexpected-import]
    )


def _install_fake_json(monkeypatch: pytest.MonkeyPatch, payload: object) -> dict[str, object]:
    """Replace ``call_json`` with a recorder returning *payload*."""
    captured: dict[str, object] = {}

    def fake_call_json(method: str, url: str, **kwargs: object) -> object:
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return payload  # ty: ignore[return-value]

    monkeypatch.setattr(providers_mod, "call_json", fake_call_json)
    return captured


def test_search_searxng_parses_vane_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Vane-shaped SearXNG JSON payload becomes SearchHits; non-http rows drop."""
    monkeypatch.setenv("SEARXNG_URL", "http://127.0.0.1:8888")
    captured = _install_fake_json(monkeypatch, _VANE_PAYLOAD)

    hits = providers_mod.search_searxng("langgraph", _spec())

    assert captured["method"] == "GET"
    assert captured["url"] == "http://127.0.0.1:8888/search"
    assert captured["params"] == {"q": "langgraph", "format": "json", "engines": "duckduckgo,bing"}
    assert [hit.url for hit in hits] == [
        "https://www.langchain.com/langgraph",
        "https://docs.searxng.org/",
    ]
    assert all(hit.searcher_id == "searxng" for hit in hits)
    assert hits[0].title == "LangGraph"
    assert hits[0].snippet.startswith("Low-level orchestration")


def test_search_searxng_fails_closed_without_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """No SEARXNG_URL and no static base_url: no HTTP call, empty hits."""
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    captured = _install_fake_json(monkeypatch, _VANE_PAYLOAD)

    hits = providers_mod.search_searxng("langgraph", _spec(base_url=None))

    assert hits == []
    assert "url" not in captured


def test_search_searxng_fails_closed_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport failure inside ``call_json`` yields empty hits, not an exception."""
    monkeypatch.setenv("SEARXNG_URL", "http://127.0.0.1:8888")

    def broken_call_json(method: str, url: str, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(providers_mod, "call_json", broken_call_json)
    assert providers_mod.search_searxng("langgraph", _spec()) == []


def test_searxng_registered_in_builtin_searchers() -> None:
    """The ``searxng`` id maps to the SearXNG implementation in the fan-out table."""
    assert builtin_searchers()["searxng"] is providers_mod.search_searxng


def test_searxng_declared_in_providers_yaml() -> None:
    """The packaged registry declares searxng as a keyless, env-based searcher."""
    spec = next(s for s in load_providers().searchers if s.id == "searxng")
    assert spec.kind == "websearcher"
    assert spec.enabled
    assert spec.base_url_env == "SEARXNG_URL"
    assert spec.engine == "duckduckgo,bing"


def test_search_pipeline_reports_ok_for_searxng(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end ``search()`` with only searxng enabled, offline via fake JSON."""
    monkeypatch.setenv("SEARXNG_URL", "http://127.0.0.1:8888")
    _install_fake_json(monkeypatch, _VANE_PAYLOAD)
    config = ProvidersConfig(version=1, searchers=(_spec(),))

    result = search("langgraph", config=config, cache_ttl_s=0)

    assert result.status["searxng"].status == "ok"
    assert any("langchain.com/langgraph" in hit.url for hit in result.hits)


def test_vane_settings_enable_json_and_wolfram() -> None:
    """The vendored Vane SearXNG settings enable JSON format and Wolfram Alpha."""
    path = Path(__file__).resolve().parents[1] / "configs" / "vane-searxng" / "settings.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "json" in data["search"]["formats"]
    assert any(
        engine.get("name") == "wolframalpha" and engine.get("disabled") is False
        for engine in data["engines"]
    )


@pytest.mark.skipif(not os.environ.get("SEARXNG_URL"), reason="SEARXNG_URL not set")
def test_searxng_live_search() -> None:
    """Live smoke test against a running SearXNG; skipped unless SEARXNG_URL is set."""
    from WebSearch.agents.agent_tools import search_hits

    hits = search_hits("langgraph handoffs", limit=3, searcher_id="searxng", timeout_s=15.0)
    assert hits, "running SearXNG instance returned no hits"
    assert all(hit.url.startswith("http") for hit in hits)
