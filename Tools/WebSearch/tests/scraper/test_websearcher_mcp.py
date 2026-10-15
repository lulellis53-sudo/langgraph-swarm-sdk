"""Tests for the WebSearcherMCP proxy tools (SearXNG, Crawl4AI)."""

from __future__ import annotations

import asyncio

import httpx2
import pytest
from WebSearch.scraper import websearcher_mcp as mod


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx2.MockTransport(handler)
    real = httpx2.AsyncClient

    class Client(real):
        def __init__(self, *a, **kw) -> None:
            super().__init__(*a, transport=transport, **kw)

    class FakeHttpx:
        AsyncClient = Client

    monkeypatch.setattr(mod, "httpx2", FakeHttpx)


def test_searxng_encodes_query(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.update(req.url.params)
        return httpx2.Response(200, json={"results": [{"title": "t", "url": "u", "content": "c"}]})

    _patch_client(monkeypatch, handler)
    out = asyncio.run(mod.searxng_web_search("a&b=c d", limit=1))
    assert seen["q"] == "a&b=c d"
    assert out.startswith("[t](u)\nc")
    assert "kept 1/" in out


def test_crawl4ai_token_from_env_only(monkeypatch: pytest.MonkeyPatch) -> None:
    auth: list[str | None] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        auth.append(req.headers.get("authorization"))
        return httpx2.Response(200, json={"results": [{"markdown": {"raw_markdown": "hi"}}]})

    _patch_client(monkeypatch, handler)
    monkeypatch.delenv("CRAWL4AI_API_TOKEN", raising=False)
    assert asyncio.run(mod.crawl4ai_scrape("http://x")) == "hi"
    monkeypatch.setenv("CRAWL4AI_API_TOKEN", "tok")
    asyncio.run(mod.crawl4ai_scrape("http://x"))
    assert auth == [None, "Bearer tok"]


def test_perplexica_requires_model_config(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PERPLEXICA_CHAT_PROVIDER_ID",
        "PERPLEXICA_CHAT_MODEL",
        "PERPLEXICA_EMBED_PROVIDER_ID",
        "PERPLEXICA_EMBED_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    assert "not configured" in asyncio.run(mod.perplexica_search("q"))


def test_deep_search_scrapes_unique_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    async def searx(q: str, limit: int = 10) -> str:
        return "[a](http://a)\nc\n\n[b](http://b)\nc"

    async def google(q: str, limit: int = 10) -> str:
        return "[a](http://a)\nc"

    scraped: list[str] = []

    async def crawl(url: str) -> str:
        scraped.append(url)
        return "page"

    monkeypatch.setattr(mod, "searxng_web_search", searx)
    monkeypatch.setattr(mod, "google_search_agent", google)
    monkeypatch.setattr(mod, "crawl4ai_scrape", crawl)
    out = asyncio.run(mod.deep_search("q", scrape_top=5, use_google=True))
    assert scraped == ["http://a", "http://b"]
    assert "## http://a" in out and "# Google" in out


def test_deep_search_never_calls_google_unless_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    async def searx(q: str, limit: int = 10) -> str:
        return "[a](http://a)\nc"

    async def google(q: str, limit: int = 10) -> str:
        raise AssertionError("Google was called without use_google=True")

    async def crawl(url: str) -> str:
        return "page"

    monkeypatch.setattr(mod, "searxng_web_search", searx)
    monkeypatch.setattr(mod, "google_search_agent", google)
    monkeypatch.setattr(mod, "crawl4ai_scrape", crawl)
    out = asyncio.run(mod.deep_search("q"))
    assert "# SearXNG" in out and "# Scraped" in out and "# Google" not in out


def test_google_agent_rotates_keys_and_parses_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    keys: list[str] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        keys.append(req.headers["x-goog-api-key"])
        if len(keys) == 1:
            return httpx2.Response(429)
        return httpx2.Response(
            200,
            json={
                "candidates": [
                    {
                        "groundingMetadata": {
                            "groundingChunks": [{"web": {"title": "T", "uri": "http://u"}}],
                            "groundingSupports": [
                                {"groundingChunkIndices": [0], "segment": {"text": "quote"}}
                            ],
                        }
                    }
                ]
            },
        )

    _patch_client(monkeypatch, handler)
    monkeypatch.setenv("GOOGLE_API_KEY", "k0")
    monkeypatch.setenv("GOOGLE_API_KEY_1", "k1")
    monkeypatch.delenv("GOOGLE_API_KEY_2", raising=False)
    assert asyncio.run(mod.google_search_agent("q")) == "[T](http://u)\nquote"
    assert keys == ["k0", "k1"]


def test_google_agent_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for n in ("GOOGLE_API_KEY", "GOOGLE_API_KEY_1", "GOOGLE_API_KEY_2"):
        monkeypatch.delenv(n, raising=False)
    assert "not configured" in asyncio.run(mod.google_search_agent("q"))


def test_google_agent_time_range_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        sent.append(__import__("json").loads(req.content))
        return httpx2.Response(200, json={})

    _patch_client(monkeypatch, handler)
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    asyncio.run(
        mod.google_search_agent("q", since="2026-01-01T00:00:00Z", until="2026-02-01T00:00:00Z")
    )
    assert sent[0]["tools"] == [
        {
            "google_search": {
                "timeRangeFilter": {
                    "startTime": "2026-01-01T00:00:00Z",
                    "endTime": "2026-02-01T00:00:00Z",
                }
            }
        }
    ]
    assert "together" in asyncio.run(mod.google_search_agent("q", since="2026-01-01T00:00:00Z"))


def test_google_agent_quota_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, lambda req: httpx2.Response(429))
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    monkeypatch.delenv("GOOGLE_API_KEY_1", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY_2", raising=False)
    assert "enable billing" in asyncio.run(mod.google_search_agent("q"))


def test_format_grounded_interactions_shape() -> None:
    text = "Spain won Euro 2024, defeating England 2-1 in the final."
    data = {
        "steps": [
            {"type": "google_search_call", "arguments": {"queries": ["x"]}},
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "text",
                        "text": text,
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "http://a",
                                "title": "a.com",
                                "start_index": 0,
                                "end_index": 9,
                            },
                            {
                                "type": "url_citation",
                                "url": "http://a",
                                "title": "a.com",
                                "start_index": 0,
                                "end_index": 9,
                            },
                        ],
                    }
                ],
            },
        ]
    }
    out = mod._format_grounded(data, 10)
    assert out.startswith(text)
    assert out.count("[a.com](http://a)") == 1
    assert "Spain won" in out.split("[a.com]")[1]
    assert mod._format_grounded({}, 5) == "No results."


def test_x_search_builds_the_documented_request(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    seen: dict = {}

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx2.Response(
            200,
            json={
                "output": [
                    {"type": "tool_call"},
                    {
                        "type": "message",
                        "content": [
                            {
                                "text": "People like it.",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://x.com/a/1",
                                        "title": "a",
                                    },
                                    {
                                        "type": "url_citation",
                                        "url": "https://x.com/a/1",
                                        "title": "a",
                                    },
                                ],
                            }
                        ],
                    },
                ],
                "citations": ["https://x.com/a/1", "https://x.com/b/2"],
            },
        )

    _patch_client(monkeypatch, handler)
    monkeypatch.setenv("XAI_API_KEY", "xai-secret")
    monkeypatch.delenv("XAI_MODEL", raising=False)
    out = asyncio.run(
        mod.x_search(
            "SpaceXAI", handles=["@alice", "bob"], from_date="2026-01-01", to_date="2026-02-01"
        )
    )
    assert seen["url"] == "https://api.x.ai/v1/responses"
    assert seen["auth"] == "Bearer xai-secret"
    assert seen["body"]["model"] == "grok-4.7"
    assert seen["body"]["input"] == [{"role": "user", "content": "SpaceXAI"}]
    assert seen["body"]["tools"] == [
        {
            "type": "x_search",
            "allowed_x_handles": ["alice", "bob"],
            "from_date": "2026-01-01",
            "to_date": "2026-02-01",
        }
    ]
    assert out.startswith("People like it.")
    assert out.count("https://x.com/a/1") == 1 and "https://x.com/b/2" in out  # de-duplicated
    assert "xai-secret" not in out


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"handles": ["bad handle"]}, "not a valid X handle"),
        ({"handles": [f"u{i}" for i in range(21)]}, "at most 20"),
        ({"from_date": "01/02/2026"}, "YYYY-MM-DD"),
        ({"from_date": "2026-03-01", "to_date": "2026-02-01"}, "after to_date"),
    ],
)
def test_x_search_rejects_bad_input_before_any_request(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict, message: str
) -> None:
    def handler(req: httpx2.Request) -> httpx2.Response:
        raise AssertionError("no request should be sent")

    _patch_client(monkeypatch, handler)
    monkeypatch.setenv("XAI_API_KEY", "k")
    assert message in asyncio.run(mod.x_search("q", **kwargs))


def test_x_search_explains_missing_key_and_out_of_credits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert "not configured" in asyncio.run(mod.x_search("q"))
    monkeypatch.setenv("XAI_API_KEY", "xai-secret")
    body = {"code": "permission-denied", "error": "team has used all available credits xai-secret"}
    _patch_client(monkeypatch, lambda req: httpx2.Response(403, json=body))
    out = asyncio.run(mod.x_search("q"))
    assert "HTTP 403" in out and "credits" in out and "xai-secret" not in out
