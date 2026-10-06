"""Regression tests for the shared-client caps, provider cache, and query cache."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from WebSearch.frontend import websearchers
from WebSearch.frontend.websearchers import SearchHit, load_providers, parallel_search
from WebSearch.midend import PrivateTarget, crawl_then_scrape, default_fetch

_PUBLIC = {"example.com": ["93.184.216.34"]}


def _public_resolver(host: str) -> list[str]:
    return _PUBLIC.get(host, [host] if host == "127.0.0.1" else [])


def test_default_fetch_caps_body_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The streaming cap keeps exactly the first ``max_bytes`` of the body."""
    payload = b"x" * 5000
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=payload))
    monkeypatch.setattr(websearchers, "_HTTP_CLIENT", httpx.Client(transport=transport))

    assert default_fetch("https://example.com/a", max_bytes=1024) == payload[:1024]
    assert default_fetch("https://example.com/a") == payload


def test_default_fetch_reports_errors_as_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP failures stay ``OSError`` so the crawler chain falls through."""
    transport = httpx.MockTransport(lambda _request: httpx.Response(500))
    monkeypatch.setattr(websearchers, "_HTTP_CLIENT", httpx.Client(transport=transport))

    with pytest.raises(OSError):
        default_fetch("https://example.com/a", max_bytes=10)


def test_default_fetch_stops_a_redirect_onto_a_private_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A public URL that redirects to loopback is refused before the body is read."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, content=b"secret")

    monkeypatch.setattr(
        websearchers, "_HTTP_CLIENT", httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(PrivateTarget, match="non-public"):
        default_fetch("https://example.com/start", public_only=True, resolver=_public_resolver)
    assert seen == ["https://example.com/start"]


def test_default_fetch_follows_a_public_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    """A redirect that stays on a public host returns that hop's body."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://example.com/landed"})
        return httpx.Response(200, content=b"landed")

    monkeypatch.setattr(
        websearchers, "_HTTP_CLIENT", httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert (
        default_fetch("https://example.com/start", public_only=True, resolver=_public_resolver)
        == b"landed"
    )


@pytest.mark.parametrize(
    "fetcher_name",
    ["fetch_httpx2", "fetch_requests", "fetch_aiohttp", "fetch_curl_cffi", "fetch_crawlee"],
)
def test_non_httpx_crawlers_refuse_non_public_urls(fetcher_name: str) -> None:
    """Requests/aiohttp/curl_cffi/httpx2/crawlee share the httpx public-URL allowlist."""
    from WebSearch import midend

    fetcher = getattr(midend, fetcher_name)
    with pytest.raises(PrivateTarget, match="non-public"):
        fetcher("file:///etc/passwd", public_only=True, resolver=_public_resolver)
    with pytest.raises(PrivateTarget, match="non-public"):
        fetcher("http://127.0.0.1/secret", public_only=True, resolver=_public_resolver)


def test_crawl_refuses_a_private_hit_without_fetching() -> None:
    """Search hits aimed at loopback are recorded as blocked, not downloaded."""
    pages = crawl_then_scrape([SearchHit("local", "http://127.0.0.1/admin", "x", "test")])
    assert len(pages) == 1
    assert pages[0].html == ""
    assert pages[0].error == "PrivateTarget"


def test_load_providers_cache_invalidates_on_rewrite(tmp_path: Path) -> None:
    """A rewritten yaml (same path) must not serve the stale cached config."""
    cfg_path = tmp_path / "providers.yaml"
    cfg_path.write_text("version: 1\nsearchers: []\n", encoding="utf-8")
    first = load_providers(cfg_path)

    cfg_path.write_text("version: 2\nsearchers: []\n", encoding="utf-8")
    second = load_providers(cfg_path)

    assert first.version == 1
    assert second.version == 2


def test_parallel_search_caches_repeated_queries() -> None:
    """The same (searcher, query) pair hits the backend only once."""
    cfg = load_providers()
    sid = cfg.searchers[0].id
    calls: list[str] = []

    def fake(query: str, _spec: object) -> list[SearchHit]:
        calls.append(query)
        return []

    for _ in range(2):
        assert parallel_search("same query", config=cfg, backends={sid: fake}) == []
    assert parallel_search("other query", config=cfg, backends={sid: fake}) == []
    assert len(calls) == 2

    parallel_search("same query", config=cfg, backends={sid: fake}, cache_ttl_s=0)
    assert len(calls) == 3
