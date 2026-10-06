"""Autonomous WebSearch: one model browses, a different model dedupes. No live API calls."""

from __future__ import annotations

import io
import itertools
import json
from pathlib import Path
from typing import Any

import pytest
from tests.scripted_chat import Script, ScriptedModel, answer
from langchain_core.messages import AIMessage
from WebSearch.browser_agent import (
    choose_playwright,
    model_key_ready,
    parse_keep,
    run_autonomous,
    select_ready,
)
from WebSearch.cli import main
from WebSearch.doctor import doctor, render
from WebSearch.frontend.websearchers import (
    DEFAULT_AUTONOMOUS_DECISION,
    DEFAULT_AUTONOMOUS_DEDUPE,
    DEFAULT_AUTONOMOUS_MEMORY,
    DEFAULT_AUTONOMOUS_PLAYWRIGHT,
    load_providers,
)

URL_A = "https://news.example.com/a"
URL_B = "https://news.example.com/b"
_RESOLVE = {"news.example.com": ["93.184.216.34"]}
_CALL_IDS = itertools.count()


def _resolver(host: str) -> list[str]:
    return _RESOLVE.get(host, [])


def _call(name: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"c{next(_CALL_IDS)}", "type": "tool_call"}],
    )


def _html(text: str) -> bytes:
    return f"<html><body><article><p>{text}</p></article></body></html>".encode()


def _browser(urls: list[str], reply: str) -> ScriptedModel:
    calls = [_call("open_page", {"url": url}) for url in urls]
    return ScriptedModel(script=Script([*calls, answer(reply)]))


def test_select_ready_skips_unready_and_the_other_role() -> None:
    names = ("alpha", "beta", "gamma")
    assert select_ready(names, ready=lambda name: name == "beta") == "beta"
    assert select_ready(names, ready=lambda name: True, skip=frozenset({"alpha"})) == "beta"
    assert select_ready(names, ready=lambda _name: False) == ""


def test_parse_keep_accepts_fenced_json_and_rejects_unknown_urls() -> None:
    urls = {URL_A, URL_B}
    raw = f'```json\n{{"keep": ["{URL_A}", "https://other.example/"]}}\n```'
    assert parse_keep(raw, urls) == [URL_A]
    assert parse_keep("not json", urls) is None
    assert parse_keep('{"keep": []}', urls) is None


def test_model_drops_a_near_duplicate_blake2b_would_keep() -> None:
    pages = {
        URL_A: _html("LightGBM wins the tabular benchmark."),
        URL_B: _html("A mirror says the tabular winner is LightGBM."),
    }
    dedupe = ScriptedModel(script=Script([answer(json.dumps({"keep": [URL_A]}))]))
    result = run_autonomous(
        "who wins?",
        playwright_model=_browser([URL_A, URL_B], f"LightGBM. Source: {URL_A}"),
        dedupe_model=dedupe,
        fetch=lambda url: pages[url],
        resolver=_resolver,
        ready=lambda _name: False,
    )
    assert result.kept == [URL_A]
    assert result.dropped == [URL_B]
    assert dedupe.script.calls == 1
    assert "untrusted data" in dedupe.script.seen[0]


def test_bad_json_falls_back_to_the_blake2b_list() -> None:
    pages = {URL_A: _html("Fact one is unique."), URL_B: _html("Fact two is different.")}
    dedupe = ScriptedModel(script=Script([answer("I refuse to use JSON")]))
    result = run_autonomous(
        "q",
        playwright_model=_browser([URL_A, URL_B], "both"),
        dedupe_model=dedupe,
        fetch=lambda url: pages[url],
        resolver=_resolver,
        ready=lambda _name: False,
    )
    assert result.kept == [URL_A, URL_B]
    assert result.dropped == []
    assert dedupe.script.calls == 1


def test_identical_pages_do_not_call_the_dedupe_model() -> None:
    html = _html("The same paragraph on two URLs.")
    dedupe = ScriptedModel(script=Script([answer('{"keep": []}')]))
    result = run_autonomous(
        "q",
        playwright_model=_browser([URL_A, URL_B], "one fact"),
        dedupe_model=dedupe,
        fetch=lambda _url: html,
        resolver=_resolver,
        ready=lambda _name: False,
    )
    assert dedupe.script.calls == 0
    assert result.kept == [URL_A]
    assert result.dropped == [URL_B]
    assert result.dedupe_model == ""


def test_providers_yaml_parses_the_two_rosters() -> None:
    cfg = load_providers()
    assert cfg.autonomous_playwright == DEFAULT_AUTONOMOUS_PLAYWRIGHT
    assert cfg.autonomous_dedupe == DEFAULT_AUTONOMOUS_DEDUPE
    assert cfg.autonomous_memory == DEFAULT_AUTONOMOUS_MEMORY == ("mem0",)
    assert cfg.autonomous_decision == DEFAULT_AUTONOMOUS_DECISION == ("jev",)
    assert set(cfg.autonomous_playwright).isdisjoint(cfg.autonomous_dedupe)


def test_missing_block_keeps_defaults_and_a_bad_list_raises(tmp_path: Path) -> None:
    bare = tmp_path / "bare.yaml"
    bare.write_text("version: 1\nsearchers: []\n", encoding="utf-8")
    cfg = load_providers(bare)
    assert cfg.autonomous_playwright == DEFAULT_AUTONOMOUS_PLAYWRIGHT
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nautonomous: [nope]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="autonomous must be a mapping"):
        load_providers(bad)


class _Memory:
    """In-memory brief store. No network and no secret values."""

    def __init__(self, hit: str | None = None) -> None:
        self.hit = hit
        self.stored: list[tuple[str, str]] = []

    def get(self, key: str) -> str | None:
        del key
        return self.hit

    def put(self, key: str, value: str) -> None:
        self.stored.append((key, value))


def test_jev_choice_can_select_a_later_ready_model() -> None:
    names = ("google:gemini-3.8-flash", "cohere:command-a")
    picked = choose_playwright(
        "q",
        names,
        ready=lambda _name: True,
        use_jev=True,
        decide=lambda _query, candidates: candidates[-1],
    )
    assert picked == "cohere:command-a"


def test_local_jev_keeps_the_first_model_when_the_query_names_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JEV_ENDPOINT", raising=False)
    picked = choose_playwright(
        "who won the race",
        ("google:gemini-3.8-flash", "cohere:command-a"),
        ready=lambda _name: True,
        use_jev=True,
    )
    assert picked == "google:gemini-3.8-flash"


def test_mem0_hit_skips_the_browser() -> None:
    browser = _browser([URL_A], "fresh answer")
    result = run_autonomous(
        "q",
        playwright_model=browser,
        memory=_Memory("saved brief"),
        fetch=lambda url: _html("page"),
        resolver=_resolver,
        ready=lambda _name: False,
    )
    assert result.answer == "saved brief"
    assert result.playwright_model == "mem0"
    assert result.memory_provider == "mem0"
    assert browser.script.calls == 0


def test_mem0_miss_stores_the_answer() -> None:
    pages = {URL_A: _html("One fact.")}
    memory = _Memory()
    result = run_autonomous(
        "q",
        playwright_model=_browser([URL_A], "the fact"),
        memory=memory,
        fetch=lambda url: pages[url],
        resolver=_resolver,
        ready=lambda _name: False,
    )
    assert result.answer == "the fact"
    assert result.memory_provider == "mem0"
    assert len(memory.stored) == 1
    assert memory.stored[0][1] == "the fact"


def test_mem0_and_jev_readiness_checks_key_names(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_get(name: str, *_args: object, **_kwargs: object) -> str | None:
        seen.append(name)
        return "present" if name == "MEM0_API_KEY" else None

    monkeypatch.setattr("swarm_sdk.vault.get", fake_get)
    monkeypatch.delenv("MEM0_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    assert model_key_ready("mem0") is True
    assert model_key_ready("jev") is False
    assert seen == ["MEM0_API_KEY", "JEV_API_KEY"]


def test_no_ready_playwright_model_raises_before_any_load() -> None:
    with pytest.raises(ValueError, match="no playwright model"):
        run_autonomous("q", ready=lambda _name: False)


def test_cli_autonomous_prints_roles_and_kept_urls() -> None:
    pages = {
        URL_A: _html("LightGBM wins the tabular benchmark."),
        URL_B: _html("A mirror says the tabular winner is LightGBM."),
    }
    dedupe = ScriptedModel(script=Script([answer(json.dumps({"keep": [URL_A]}))]))
    out = io.StringIO()
    code = main(
        ["--prompt", "q", "--autonomous"],
        model=_browser([URL_A, URL_B], f"Answer from {URL_A}"),
        dedupe_model=dedupe,
        fetch=lambda url: pages[url],
        resolver=_resolver,
        ready=lambda name: name.startswith("openrouter:") or name.startswith("mistral:"),
        out=out,
    )
    text = out.getvalue()
    assert code == 0
    assert "playwright: openrouter:z-ai/glm-5.3-flash" in text
    assert "dedupe: mistral:ministral-3-8b-latest" in text
    assert f"kept: {URL_A}" in text
    assert f"dropped: {URL_B}" in text


def test_cli_autonomous_without_a_ready_model_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--prompt", "q", "--autonomous"], ready=lambda _name: False) == 2
    assert "no playwright model" in capsys.readouterr().err


def test_doctor_lists_roster_readiness_without_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "WebSearch.browser_agent.model_key_ready",
        lambda name: name == "openrouter:z-ai/glm-5.3-flash",
    )
    report = doctor()
    auto = report["autonomous"]
    assert auto["selected_playwright"] == "openrouter:z-ai/glm-5.3-flash"
    assert auto["selected_dedupe"] == ""
    text = render(report)
    assert "autonomous playwright:" in text
    assert "not-ready" in text
    assert "secret" not in text.lower()


def test_model_key_ready_checks_the_registry_name_not_the_secret_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stand-in vault returns a non-empty value. The assertion never sees that value."""
    seen: list[str] = []

    def route() -> dict[str, tuple[str, str]]:
        return {"openrouter:z-ai/glm-5.3-flash": ("OPENROUTER_API_KEY", "")}

    def fake_get(name: str) -> str | None:
        seen.append(name)
        return "present" if name == "OPENROUTER_API_KEY" else None

    monkeypatch.setattr("swarm_sdk.models.chat._route_index", route)
    monkeypatch.setattr("swarm_sdk.vault.get", fake_get)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert model_key_ready("openrouter:z-ai/glm-5.3-flash") is True
    assert model_key_ready("missing:nope") is False
    assert model_key_ready("grok-cli:grok-4.6") is True
    assert seen == ["OPENROUTER_API_KEY"]
