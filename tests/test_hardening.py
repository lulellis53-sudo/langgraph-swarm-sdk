"""Regression tests for the shared-client caps, provider cache, and query cache."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from WebSearch.frontend import websearchers
from WebSearch.frontend.websearchers import SearchHit, load_providers, parallel_search
from WebSearch.midend import default_fetch


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
