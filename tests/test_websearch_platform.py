"""Dork engine, providers file (yaml/json), crawlers, doctor, browser agent and API."""

from __future__ import annotations

import http.server
import io
import itertools
import json
import threading
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from tests.scripted_chat import Script, ScriptedModel, answer
from WebSearch import midend
from WebSearch.api import create_app
from WebSearch.browser_agent import BrowseError, browse, is_public_http_url
from WebSearch.cli import build_parser, build_query, main
from WebSearch.doctor import doctor, render
from WebSearch.frontend import websearchers as ws
from WebSearch.frontend.dorks import DorkError, dork, parse_dork
from WebSearch.frontend.websearchers import CrawlerName, SearcherSpec, SearchHit, load_providers
from WebSearch.langchain_tools import websearch_langchain_tools
from WebSearch.midend import PrivateTarget

# ---------------------------------------------------------------- dorks


def test_dork_supports_intext_exact_phrases_and_excluded_sites() -> None:
    query = dork(
        "lightgbm",
        exact=["gradient boosting"],
        intext="benchmark",
        exclude_sites=["pinterest.com"],
        after="2026-06-01",
    )
    assert query == (
        '(lightgbm) AND "gradient boosting" intext:benchmark -site:pinterest.com after:2026-06-01'
    )


def test_dork_needs_a_group_or_a_phrase() -> None:
    with pytest.raises(DorkError):
        dork()
    assert dork(exact=["only phrase"]) == '"only phrase"'


def test_parse_dork_is_the_inverse_of_dork() -> None:
    query = dork(
        "a",
        ["b", "c d"],
        site="github.com",
        filetype="pdf",
        exclude_sites=["x.com"],
        exclude=["jobs"],
        after="2026-06-01",
        before="2026-07-01",
    )
    parsed = parse_dork(query)
    assert parsed.terms == ("a", "b", "c d")
    assert parsed.sites == ("github.com",) and parsed.exclude_sites == ("x.com",)
    assert parsed.exclude_terms == ("jobs",) and parsed.filetype == "pdf"
    assert (parsed.after, parsed.before) == ("2026-06-01", "2026-07-01")
    assert parsed.plain() == "a b c d pdf"


def test_parse_dork_keeps_bad_dates_and_unknown_operators_as_terms() -> None:
    parsed = parse_dork("x after:2026-13-45 foo:bar")
    assert parsed.after is None
    assert parsed.terms == ("x", "after:2026-13-45", "foo:bar")


# ---------------------------------------------------------------- providers file


def _write_json(tmp_path: Path, **extra: Any) -> Path:
    data = {
        "version": 1,
        "searchers": [
            {"id": "tavily", "kind": "websearcher", "dork": "translate", "api_key_env": "K"},
            {"id": "ddg", "kind": "websearcher"},
        ],
        "dork_presets": {"recent": {"after_days": 3}, "repos": {"site": "github.com"}},
        "llm": {"model": "zai:test", "max_pages": 2, "max_chars": 50},
        **extra,
    }
    path = tmp_path / "providers.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_providers_load_from_json(tmp_path: Path) -> None:
    cfg = load_providers(_write_json(tmp_path))
    assert [(s.id, s.dork) for s in cfg.searchers] == [("tavily", "translate"), ("ddg", "native")]
    assert cfg.dork_presets["repos"] == {"site": "github.com"}
    assert (cfg.llm.model, cfg.llm.max_pages, cfg.llm.max_chars) == ("zai:test", 2, 50)


def test_invalid_json_and_bad_dork_mode_raise_value_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_providers(bad)
    with pytest.raises(ValueError, match="dork must be"):
        load_providers(_write_json(tmp_path, searchers=[{"id": "x", "dork": "bogus"}]))


def test_env_overrides_path_and_llm_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write_json(tmp_path)
    monkeypatch.setenv("WEBSEARCH_PROVIDERS", str(path))
    monkeypatch.setenv("WEBSEARCH_LLM_MODEL", "openai:override")
    cfg = load_providers()
    assert cfg.llm.model == "openai:override"
    assert [s.id for s in cfg.searchers] == ["tavily", "ddg"]


def test_shipped_providers_file_has_translate_mode_and_presets() -> None:
    cfg = load_providers(ws.providers_yaml_path())
    modes = {s.id: s.dork for s in cfg.searchers}
    assert modes["tavily"] == modes["exa"] == "translate"
    assert {"last_week", "papers", "github"} <= set(cfg.dork_presets)
    assert "curl_cffi" in cfg.crawl.crawler_order


# ---------------------------------------------------------------- translate to API fields


def _capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake(method: str, url: str, **kwargs: Any) -> Any:
        seen["url"], seen["body"] = url, kwargs.get("json_body")
        return {"results": []}

    monkeypatch.setattr(ws, "_httpx_json", fake)
    monkeypatch.setattr(ws, "env_key", lambda spec: "secret")
    return seen


DORK = dork(
    "lightgbm", site="github.com", exclude_sites=["x.com"], after="2026-06-01", before="2026-07-01"
)


def test_tavily_translate_maps_operators_to_api_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch)
    ws.search_tavily(DORK, SearcherSpec("tavily", "websearcher", dork="translate"))
    body = seen["body"]
    assert body["query"] == "lightgbm"
    assert body["include_domains"] == ["github.com"] and body["exclude_domains"] == ["x.com"]
    assert (body["start_date"], body["end_date"]) == ("2026-06-01", "2026-07-01")


def test_exa_translate_maps_operators_to_api_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch)
    ws.search_exa(DORK, SearcherSpec("exa", "websearcher", dork="translate"))
    body = seen["body"]
    assert body["query"] == "lightgbm"
    assert body["includeDomains"] == ["github.com"] and body["excludeDomains"] == ["x.com"]
    assert (body["startPublishedDate"], body["endPublishedDate"]) == ("2026-06-01", "2026-07-01")


def test_native_mode_sends_the_dork_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch)
    ws.search_tavily(DORK, SearcherSpec("tavily", "websearcher"))
    assert seen["body"]["query"] == DORK and "start_date" not in seen["body"]


# ---------------------------------------------------------------- crawlers


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/missing":
            self.send_response(404)
            self.end_headers()
            return
        body = b"<html>" + b"x" * 1000 + b"</html>"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@pytest.fixture
def local_server() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


@pytest.mark.parametrize("name", ["httpx", "httpx2", "requests", "aiohttp", "curl_cffi"])
def test_http_crawlers_fetch_cap_and_report_errors(name: CrawlerName, local_server: str) -> None:
    full = midend._fetch_named(name, f"{local_server}/", 10.0)
    assert full.startswith(b"<html>") and len(full) == 1013
    capped = midend._fetch_named(name, f"{local_server}/", 10.0, max_bytes=100)
    if name != "httpx":  # the shared httpx client already honors the cap too
        assert len(capped) == 100
    with pytest.raises(OSError):
        midend._fetch_named(name, f"{local_server}/missing", 10.0)


def test_capped_helper_stops_at_the_limit() -> None:
    assert midend._capped([b"abc", b"def"], 4) == b"abcd"
    assert midend._capped([b"abc", b"def"], None) == b"abcdef"


# ---------------------------------------------------------------- doctor


def test_doctor_reports_crawlers_extractors_and_searchers() -> None:
    report = doctor()
    names = {c["name"] for c in report["crawlers"]}
    assert {"httpx", "curl_cffi", "playwright"} <= names
    assert {e["name"] for e in report["extractors"]} >= {"selectolax", "trafilatura", "bs4"}
    assert any(s["id"] == "tavily" and s["dork"] == "translate" for s in report["searchers"])
    text = render(report)
    assert "crawlers:" in text and "searchers:" in text and "secret" not in text.lower()


# ---------------------------------------------------------------- browser agent

PUBLIC = "https://news.example.com/story"
RESOLVE = {"news.example.com": ["93.184.216.34"], "internal.example": ["10.0.0.5"]}


def _resolver(host: str) -> list[str]:
    return RESOLVE.get(host, [])


_CALL_IDS = itertools.count()


def _call(name: str, args: dict[str, Any], tokens: int = 10) -> AIMessage:
    # LangGraph treats a tool call whose id already has a ToolMessage as done, so ids are unique.
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"c{next(_CALL_IDS)}", "type": "tool_call"}],
        usage_metadata={"input_tokens": 1, "output_tokens": tokens - 1, "total_tokens": tokens},
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (PUBLIC, True),
        ("http://127.0.0.1:8888/", False),
        ("http://localhost/", False),
        ("http://192.168.1.10/", False),
        ("http://[::1]/", False),
        ("file:///etc/passwd", False),
        ("ftp://news.example.com/x", False),
        ("https://internal.example/x", False),  # resolves to a private address
        ("https://unresolvable.invalid/", False),
        ("not a url", False),
    ],
)
def test_is_public_http_url(url: str, expected: bool) -> None:
    assert is_public_http_url(url, resolver=_resolver) is expected


PAGE = (
    b"<html><body><article><p>"
    + b"LightGBM wins the benchmark. " * 40
    + b"</p></article></body></html>"
)


def test_agent_opens_a_public_page_and_answers_from_it() -> None:
    model = ScriptedModel(
        script=Script(
            [_call("open_page", {"url": PUBLIC}), answer(f"LightGBM wins. Source: {PUBLIC}")]
        )
    )
    opened: list[str] = []

    def fake_fetch(url: str) -> bytes:
        opened.append(url)
        return PAGE

    result = browse("who wins?", model=model, fetch=fake_fetch, resolver=_resolver)
    assert opened == [PUBLIC] and result.pages == [PUBLIC]
    assert PUBLIC in result.answer and result.stopped == ""
    assert result.model_tokens == 10


def test_agent_blocks_a_redirect_that_lands_on_a_private_host() -> None:
    """The fetch reports a private landing URL; the page text is not returned."""

    def fake_fetch(url: str) -> bytes:
        raise PrivateTarget("non-public host refused")

    result = browse(
        "q",
        model=ScriptedModel(script=Script([_call("open_page", {"url": PUBLIC}), answer("unused")])),
        fetch=fake_fetch,
        resolver=_resolver,
    )
    assert result.pages == []
    assert result.blocked == [PUBLIC]


def test_agent_is_blocked_from_private_and_local_urls() -> None:
    model = ScriptedModel(
        script=Script([_call("open_page", {"url": "http://127.0.0.1:8888/"}), answer("done")])
    )
    fetched: list[str] = []
    result = browse("q", model=model, fetch=lambda u: fetched.append(u) or PAGE, resolver=_resolver)
    assert fetched == [] and result.pages == []
    assert result.blocked == ["http://127.0.0.1:8888/"]


def test_agent_respects_the_page_budget_and_truncates_text(tmp_path: Path) -> None:
    cfg = load_providers(_write_json(tmp_path))  # max_pages 2, max_chars 50
    urls = [f"https://news.example.com/{i}" for i in range(3)]
    model = ScriptedModel(
        script=Script([*[_call("open_page", {"url": u}) for u in urls], answer("ok")])
    )
    seen_text: list[str] = []
    result = browse("q", model=model, config=cfg, fetch=lambda u: PAGE, resolver=_resolver)
    assert result.pages == urls[:2] and result.blocked == [urls[2]]
    seen_text.extend(model.script.seen)
    page_messages = [t for t in seen_text if t.startswith("[PAGE")]
    assert page_messages and all(
        len(t) < 50 + len("[PAGE ] [END PAGE]") + 60 for t in page_messages
    )


def test_agent_stops_at_the_step_budget() -> None:
    loop = ScriptedModel(script=Script([_call("open_page", {"url": PUBLIC}) for _ in range(50)]))
    result = browse(
        "q",
        model=loop,
        config=load_providers(),
        fetch=lambda u: PAGE,
        resolver=_resolver,
    )
    assert result.stopped == "max_steps" and result.answer == ""


class _BrokenModel(ScriptedModel):
    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        raise PermissionError("401 invalid api key")


def test_provider_failure_becomes_a_browse_error_and_exit_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    broken = _BrokenModel(script=Script([answer("never")]))
    with pytest.raises(BrowseError, match="PermissionError: 401"):
        browse("q", model=broken)
    assert main(["--prompt", "q", "--browse"], model=broken) == 2
    assert "PermissionError: 401" in capsys.readouterr().err


def test_agent_without_a_model_raises(tmp_path: Path) -> None:
    cfg = load_providers(_write_json(tmp_path, llm={"model": ""}))
    with pytest.raises(ValueError, match="no chat model"):
        browse("q", config=cfg)


def test_agent_web_search_uses_the_providers() -> None:
    def search(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [SearchHit("Hit title", "https://a.example/1", "snippet text here", spec.id)]

    model = ScriptedModel(
        script=Script([_call("web_search", {"query": "site:a.example lightgbm"}), answer("done")])
    )
    result = browse("q", model=model, backends={"ddg": search}, resolver=_resolver)
    assert result.searches == ["site:a.example lightgbm"]
    assert any("a.example/1" in t for t in model.script.seen)


# ---------------------------------------------------------------- CLI


def test_preset_days_and_explicit_flags_build_the_dork(tmp_path: Path) -> None:
    cfg = load_providers(_write_json(tmp_path))
    parse = build_parser().parse_args
    today = date.today()
    q = build_query(parse(["--prompt", "lightgbm", "--preset", "repos"]), cfg.dork_presets)
    assert q == "(lightgbm) site:github.com"
    q = build_query(parse(["--prompt", "x", "--preset", "recent"]), cfg.dork_presets)
    assert q == f"(x) after:{(today - timedelta(days=3)).isoformat()}"
    q = build_query(
        parse(["--prompt", "x", "--preset", "repos", "--site", "gitlab.com", "--days", "1"]),
        cfg.dork_presets,
    )
    assert q == f"(x) site:gitlab.com after:{(today - timedelta(days=1)).isoformat()}"
    with pytest.raises(DorkError, match="unknown preset"):
        build_query(parse(["--prompt", "x", "--preset", "nope"]), cfg.dork_presets)


def test_cli_uses_a_json_providers_file(tmp_path: Path) -> None:
    path = _write_json(tmp_path)
    out = io.StringIO()

    def search(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [SearchHit("t", "https://a.example/1", "snippet text", spec.id)]

    code = main(
        ["--prompt", "x", "--providers", str(path), "--json", "--report"],
        backends={"ddg": search},
        out=out,
    )
    data = json.loads(out.getvalue())
    assert code == 0
    assert {p["id"] for p in data["providers"]} == {"tavily", "ddg"}  # only the file's searchers


def test_cli_doctor_needs_no_prompt() -> None:
    out = io.StringIO()
    assert main(["--doctor"], out=out) == 0
    assert "crawlers:" in out.getvalue()


def test_cli_without_prompt_or_doctor_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2 and "--prompt is required" in capsys.readouterr().err


def test_cli_browse_prints_answer_and_audit_trail() -> None:
    model = ScriptedModel(
        script=Script([_call("open_page", {"url": PUBLIC}), answer(f"Answer from {PUBLIC}")])
    )
    out = io.StringIO()
    code = main(
        ["--prompt", "q", "--browse"],
        model=model,
        fetch=lambda u: PAGE,
        resolver=_resolver,
        out=out,
    )
    text = out.getvalue()
    assert code == 0 and f"opened: {PUBLIC}" in text and "model tokens: 10" in text


def test_cli_browse_without_model_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_json(tmp_path, llm={"model": ""})
    assert main(["--prompt", "q", "--browse", "--providers", str(path)]) == 2
    assert "no chat model" in capsys.readouterr().err


# ---------------------------------------------------------------- API


def _client(**kwargs: Any) -> TestClient:
    return TestClient(create_app(**kwargs))


def test_api_health_doctor_and_presets() -> None:
    client = _client()
    assert client.get("/health").json() == {"status": "ok"}
    assert "crawlers" in client.get("/doctor").json()
    assert "last_week" in client.get("/presets").json()


def test_api_agents_lists_summarize_and_dedupe() -> None:
    client = _client()
    assert {agent["name"] for agent in client.get("/Agents").json()["agents"]} == {
        "summarize",
        "dedupe",
    }
    documents = [
        {"url": "https://a.example", "text": "LightGBM builds gradient boosted trees."},
        {"url": "https://b.example", "text": "lightgbm builds gradient boosted trees."},
        {"url": "https://c.example", "text": "Cats sleep all day in warm places."},
    ]
    deduped = client.post("/Agents", json={"action": "dedupe", "documents": documents})
    assert deduped.status_code == 200
    assert deduped.json()["removed"] == 1
    summarized = client.post(
        "/Agents",
        json={"action": "summarize", "query": "lightgbm forecasting", "documents": documents},
    )
    assert summarized.status_code == 200
    assert summarized.json()["results"][0]["url"] == "https://a.example"


def test_api_summarize_agent_requires_query() -> None:
    response = _client().post("/Agents", json={"action": "summarize", "documents": []})
    assert response.status_code == 422


def test_langchain_tools_include_semantic_summarize_and_dedupe() -> None:
    tools = {tool.name: tool for tool in websearch_langchain_tools()}
    assert set(tools) == {
        "web_search_brief",
        "web_search_hits",
        "web_dedupe_documents",
        "web_summarize_documents",
    }
    documents = [
        {"url": "https://a.example", "text": "LightGBM builds gradient boosted trees."},
        {"url": "https://b.example", "text": "lightgbm builds gradient boosted trees."},
        {"url": "https://c.example", "text": "Cats sleep all day in warm places."},
    ]
    deduped = tools["web_dedupe_documents"].invoke({"documents": documents})
    assert deduped["removed"] == 1
    summarized = tools["web_summarize_documents"].invoke(
        {"query": "lightgbm forecasting", "documents": documents}
    )
    assert summarized["results"][0]["url"] == "https://a.example"


def test_api_search_returns_hits_and_translates_options() -> None:
    queries: list[str] = []

    def search(query: str, spec: SearcherSpec) -> list[SearchHit]:
        queries.append(query)
        return [SearchHit("t", "https://a.example/1", "snippet text", spec.id)]

    client = _client(backends={"ddg": search})
    response = client.post(
        "/search",
        json={"prompt": "lightgbm", "site": "github.com", "after": "2026-06-01", "report": True},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["query"] == "(lightgbm) site:github.com after:2026-06-01"
    assert body["hits"] and body["providers"]
    assert queries == [body["query"]]


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": "x", "after": "2026-13-01"},
        {"prompt": "x", "preset": "nope"},
        {"prompt": "x", "searcher": "nosuch"},
    ],
)
def test_api_search_maps_bad_input_to_422(payload: dict[str, Any]) -> None:
    assert _client(backends={}).post("/search", json=payload).status_code == 422


def test_api_search_validates_the_body_and_has_no_write_options() -> None:
    client = _client(backends={})
    assert client.post("/search", json={"prompt": ""}).status_code == 422
    assert client.post("/search", json={"prompt": "x", "limit": 500}).status_code == 422
    response = client.post("/search", json={"prompt": "x", "db": "/tmp/evil.db", "route": "sql"})
    assert response.status_code == 200 and "routes" not in response.json()


def test_api_browse_runs_the_agent_with_the_injected_model() -> None:
    model = ScriptedModel(script=Script([_call("open_page", {"url": PUBLIC}), answer("final")]))
    client = _client(model_factory=lambda: model, fetch=lambda u: PAGE)
    # the default resolver does DNS, so use a literal public IP host
    model.script.messages[0] = _call("open_page", {"url": "http://93.184.216.34/"})
    body = client.post("/browse", json={"question": "q"}).json()
    assert body["answer"] == "final" and body["pages"] == ["http://93.184.216.34/"]


def test_api_browse_without_a_model_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    cfg = load_providers(ws.providers_yaml_path())
    no_model = replace(cfg, llm=replace(cfg.llm, model=""))
    monkeypatch.setattr("WebSearch.api.load_providers", lambda: no_model)
    assert _client().post("/browse", json={"question": "q"}).status_code == 422


# ---------------------------------------------------------------- google_ground keys


def _gemini_spec(*fallbacks: str) -> SearcherSpec:
    return SearcherSpec(
        "google_ground",
        "websearcher",
        api_key_env="GK1",
        engine="gemini-3.8-flash",
        api_key_fallback_envs=fallbacks,
    )


GROUNDED = {
    "candidates": [
        {
            "groundingMetadata": {
                "webSearchQueries": ["q1", "q2"],
                "groundingChunks": [{"web": {"uri": "https://a.example/1", "title": "A"}}],
                "groundingSupports": [
                    {"segment": {"text": "A cited sentence."}, "groundingChunkIndices": [0]}
                ],
            }
        }
    ],
    "usageMetadata": {"totalTokenCount": 77},
}


@pytest.fixture
def gemini_keys(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Resolve GK1/GK2 from a dict and record which key each request used."""
    monkeypatch.setattr(
        ws, "_resolve_secret", lambda name: {"GK1": "key-one", "GK2": "key-two"}.get(name, "")
    )
    return []


def _fake_request(used: list[str], outcomes: dict[str, Any]):
    def fake(method: str, url: str, **kwargs: Any) -> Any:
        key = kwargs["headers"]["x-goog-api-key"]
        used.append(key)
        outcome = outcomes[key]
        if isinstance(outcome, Exception):
            raise outcome
        assert url.endswith("/models/gemini-3.8-flash:generateContent")
        assert kwargs["json_body"]["tools"] == [{"google_search": {}}]
        return outcome

    return fake


def test_env_keys_orders_primary_then_fallbacks_and_skips_missing_and_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets = {"GK1": "same", "GK2": "same", "GK3": "other"}
    monkeypatch.setattr(ws, "_resolve_secret", lambda name: secrets.get(name, ""))
    assert ws.env_keys(_gemini_spec("GK2", "GK3", "NOPE")) == ["same", "other"]
    assert ws.env_key(_gemini_spec("GK2")) == "same"
    assert ws.env_keys(SearcherSpec("x", "websearcher")) == []


def test_google_ground_rotates_to_the_second_key_on_401_and_429(
    monkeypatch: pytest.MonkeyPatch, gemini_keys: list[str]
) -> None:
    for status in ("401 Unauthorized", "429 Too Many Requests"):
        used: list[str] = []
        outcomes = {"key-one": OSError(f"Client error '{status}'"), "key-two": GROUNDED}
        monkeypatch.setattr(ws, "request_json", _fake_request(used, outcomes))
        hits = ws.search_google_ground("q", _gemini_spec("GK2"))
        assert used == ["key-one", "key-two"], status
        assert [h.url for h in hits] == ["https://a.example/1"]
        assert hits[0].api_tokens == 77 and hits[0].snippet == "A cited sentence."


def test_google_ground_stops_on_a_non_auth_error_and_when_every_key_fails(
    monkeypatch: pytest.MonkeyPatch, gemini_keys: list[str]
) -> None:
    used: list[str] = []
    outcomes = {"key-one": OSError("Server error '500 Internal Server Error'"), "key-two": GROUNDED}
    monkeypatch.setattr(ws, "request_json", _fake_request(used, outcomes))
    assert ws.search_google_ground("q", _gemini_spec("GK2")) == []
    assert used == ["key-one"]  # a 500 is not a key problem: no rotation

    used.clear()
    both_bad = {"key-one": OSError("401 Unauthorized"), "key-two": OSError("403 Forbidden")}
    monkeypatch.setattr(ws, "request_json", _fake_request(used, both_bad))
    assert ws.search_google_ground("q", _gemini_spec("GK2")) == []
    assert used == ["key-one", "key-two"]


def test_google_ground_without_any_key_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws, "_resolve_secret", lambda name: "")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("must not call the API without a key")

    monkeypatch.setattr(ws, "request_json", boom)
    assert ws.search_google_ground("q", _gemini_spec("GK2")) == []


def test_shipped_google_ground_has_a_fallback_key_and_current_model() -> None:
    spec = next(
        s for s in load_providers(ws.providers_yaml_path()).searchers if s.id == "google_ground"
    )
    assert spec.api_key_fallback_envs == ("GOOGLE_API_KEY", "GEMINI_API_KEY_2")
    assert spec.engine == "gemini-3.8-flash"
