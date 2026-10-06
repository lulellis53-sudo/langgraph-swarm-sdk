"""CLI-backed chat models (claude -p, codex exec) and the OpenRouter web-search provider."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from WebSearch.browser_agent import browse
from WebSearch.frontend import websearchers as ws
from WebSearch.frontend.websearchers import SearcherSpec

from swarm_sdk.models import cli_chat
from swarm_sdk.models.chat import load_chat_model
from swarm_sdk.models.cli_chat import CliChatModel, CliError, load_cli_model, parse_reply

# ---------------------------------------------------------------- reply parsing


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ('{"final": "the answer"}', ("the answer", None)),
        ('```json\n{"final": "fenced"}\n```', ("fenced", None)),
        (
            '{"tool": "open_page", "args": {"url": "https://a.example"}}',
            ("", {"name": "open_page", "args": {"url": "https://a.example"}}),
        ),
        (
            'Sure! {"tool": "web_search", "args": {"query": "x"}} done',
            ("", {"name": "web_search", "args": {"query": "x"}}),
        ),
        ('{"tool": "web_search"}', ("", {"name": "web_search", "args": {}})),
        ("just prose, no json", ("just prose, no json", None)),
        ('{"unrelated": 1}', ('{"unrelated": 1}', None)),
        ("{broken json", ("{broken json", None)),
    ],
)
def test_parse_reply(reply: str, expected: tuple[str, dict[str, Any] | None]) -> None:
    assert parse_reply(reply) == expected


# ---------------------------------------------------------------- the model


class _Runner:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, argv: Sequence[str], stdin: str, timeout: float) -> str:
        self.calls.append((list(argv), stdin))
        return self.replies.pop(0)


def _claude_json(text: str, **usage: int) -> str:
    return json.dumps({"result": text, "usage": usage, "is_error": False})


@tool
def open_page(url: str) -> str:
    """Open a page."""
    return f"page {url}"


def test_plain_reply_and_token_usage_from_claude_json() -> None:
    runner = _Runner(
        _claude_json("OK", input_tokens=10, output_tokens=2, cache_read_input_tokens=5)
    )
    model = CliChatModel(provider="claude-cli", runner=runner)
    reply = model.invoke([SystemMessage("be brief"), HumanMessage("say OK")])
    assert reply.content == "OK" and reply.tool_calls == []
    assert reply.usage_metadata is not None and reply.usage_metadata["total_tokens"] == 17
    argv, stdin = runner.calls[0]
    assert argv[:2] == ["claude", "-p"] and "--bare" not in argv  # --bare would drop the login
    assert argv[argv.index("--tools") + 1] == "" and "--no-session-persistence" in argv
    assert "SYSTEM: be brief" in stdin and "HUMAN: say OK" in stdin  # prompt is on stdin only


def test_bound_tools_get_the_json_protocol_and_return_tool_calls() -> None:
    runner = _Runner(
        _claude_json('{"tool": "open_page", "args": {"url": "https://a.example"}}'),
        _claude_json('{"final": "done"}'),
    )
    model = CliChatModel(provider="claude-cli", runner=runner).bind_tools([open_page])
    first = model.invoke([HumanMessage("read it")])
    assert first.tool_calls[0]["name"] == "open_page"
    assert first.tool_calls[0]["args"] == {"url": "https://a.example"}
    assert "open_page" in runner.calls[0][1] and "EXACTLY one JSON object" in runner.calls[0][1]
    tool_message = ToolMessage(
        "page text", name="open_page", tool_call_id=first.tool_calls[0]["id"]
    )
    second = model.invoke([HumanMessage("read it"), first, tool_message])
    assert second.content == "done" and second.tool_calls == []
    assert "TOOL RESULT (open_page):\npage text" in runner.calls[1][1]


def test_empty_reply_and_cli_errors_raise_cli_error() -> None:
    with pytest.raises(CliError, match="empty reply"):
        CliChatModel(provider="codex-cli", runner=_Runner("   \n")).invoke("hi")
    with pytest.raises(CliError, match="non-JSON"):
        CliChatModel(provider="claude-cli", runner=_Runner("not json")).invoke("hi")
    error = json.dumps({"is_error": True, "result": "Credit balance is too low"})
    with pytest.raises(CliError, match="Credit balance"):
        CliChatModel(provider="claude-cli", runner=_Runner(error)).invoke("hi")


def test_codex_argv_supports_model_and_profile() -> None:
    plain = cli_chat._codex_argv("default")
    assert plain[:3] == ["codex", "exec", "--skip-git-repo-check"] and "-p" not in plain
    assert "-s" in plain and plain[plain.index("-s") + 1] == "read-only"
    assert cli_chat._codex_argv("profile:fast")[-2:] == ["-p", "fast"]
    assert cli_chat._codex_argv("gpt-x")[-2:] == ["-m", "gpt-x"]


def test_load_chat_model_routes_cli_providers_without_keys() -> None:
    model = load_chat_model("claude-cli:default")
    assert isinstance(model, CliChatModel) and model.provider == "claude-cli"
    assert load_chat_model("codex-cli:profile:work").model == "profile:work"
    with pytest.raises(ValueError, match="unknown CLI provider"):
        load_cli_model("gemini-cli")


def test_subprocess_child_does_not_inherit_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("KEEP_ME", "yes")
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="out", stderr="")

    monkeypatch.setattr(cli_chat.subprocess, "run", fake_run)
    assert cli_chat.run_subprocess(["claude", "-p"], "prompt", 5.0) == "out"
    assert "ANTHROPIC_API_KEY" not in seen["env"] and "OPENAI_API_KEY" not in seen["env"]
    assert seen["env"]["KEEP_ME"] == "yes" and seen["input"] == "prompt"
    assert seen["cwd"] != "." and seen["timeout"] == 5.0


def test_subprocess_failures_become_cli_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom\nusage limit hit")

    monkeypatch.setattr(cli_chat.subprocess, "run", failing)
    with pytest.raises(CliError, match="exited 1: boom usage limit hit"):  # no error line: tail
        cli_chat.run_subprocess(["codex", "exec"], "p", 5.0)

    def missing(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("codex")

    monkeypatch.setattr(cli_chat.subprocess, "run", missing)
    with pytest.raises(CliError, match="FileNotFoundError"):
        cli_chat.run_subprocess(["codex", "exec"], "p", 5.0)


def test_browser_agent_runs_on_a_cli_model_through_the_json_protocol() -> None:
    url = "https://news.example.com/story"
    runner = _Runner(
        _claude_json(json.dumps({"tool": "open_page", "args": {"url": url}})),
        _claude_json(json.dumps({"final": f"LightGBM is a boosting library. Source: {url}"})),
    )
    page = (
        b"<html><body><article><p>"
        + b"LightGBM is a boosting library. " * 20
        + b"</p></article></body></html>"
    )
    result = browse(
        "what is it?",
        model=CliChatModel(provider="claude-cli", runner=runner),
        fetch=lambda u: page,
        resolver=lambda host: ["93.184.216.34"],
    )
    assert result.pages == [url] and url in result.answer and result.stopped == ""


# ---------------------------------------------------------------- OpenRouter web search


def _spec(**kwargs: Any) -> SearcherSpec:
    return SearcherSpec("openrouter_web", "websearcher", api_key_env="K", engine="m/free", **kwargs)


NESTED = {
    "choices": [
        {
            "message": {
                "content": "x",
                "annotations": [
                    {
                        "type": "url_citation",
                        "url_citation": {
                            "url": "https://a.example/1",
                            "title": "A",
                            "content": "about a",
                        },
                    },
                    {
                        "type": "url_citation",
                        "url_citation": {"url": "https://a.example/1", "title": "dup"},
                    },
                    {
                        "type": "url_citation",
                        "url": "https://b.example/2",
                    },  # flat (Responses style)
                    {"type": "other", "url": "https://skip.example"},
                ],
            }
        }
    ],
    "usage": {"total_tokens": 321},
}


def test_openrouter_web_parses_citations_dedupes_and_reports_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake(method: str, url: str, **kwargs: Any) -> Any:
        seen.update(url=url, body=kwargs["json_body"], headers=kwargs["headers"])
        return NESTED

    monkeypatch.setattr(ws, "_resolve_secret", lambda name: "or-key" if name == "K" else "")
    monkeypatch.setattr(ws, "_httpx_json", fake)
    hits = ws.search_openrouter_web("lightgbm", _spec())
    assert [h.url for h in hits] == ["https://a.example/1", "https://b.example/2"]
    assert hits[0].title == "A" and hits[0].snippet == "about a" and hits[0].api_tokens == 321
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["body"]["model"] == "m/free" and seen["body"]["plugins"][0]["id"] == "web"
    assert seen["headers"]["Authorization"] == "Bearer or-key"


def test_openrouter_web_translates_site_operators(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(ws, "_resolve_secret", lambda name: "k")
    monkeypatch.setattr(ws, "_httpx_json", lambda *a, **k: seen.update(body=k["json_body"]) or {})
    ws.search_openrouter_web("lightgbm site:github.com -site:x.com", _spec(dork="translate"))
    plugin = seen["body"]["plugins"][0]
    assert plugin["include_domains"] == ["github.com"] and plugin["exclude_domains"] == ["x.com"]
    assert "lightgbm" in seen["body"]["messages"][0]["content"]
    assert "site:" not in seen["body"]["messages"][0]["content"]


def test_openrouter_web_without_key_or_on_failure_returns_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ws, "_resolve_secret", lambda name: "")
    assert ws.search_openrouter_web("q", _spec()) == []
    monkeypatch.setattr(ws, "_resolve_secret", lambda name: "k")
    monkeypatch.setattr(ws, "_httpx_json", lambda *a, **k: None)
    assert ws.search_openrouter_web("q", _spec()) == []


def test_shipped_config_registers_openrouter_web_and_an_agent_model() -> None:
    cfg = ws.load_providers(ws.providers_yaml_path())
    entry = next(s for s in cfg.searchers if s.id == "openrouter_web")
    assert entry.dork == "translate" and entry.api_key_env == "OPENROUTER_API_KEY"
    assert "openrouter_web" in ws.builtin_searchers()
    assert cfg.llm.model  # a chat model is configured (any provider:name, CLI or API)


# ---------------------------------------------------------------- grok CLI


def test_grok_argv_reads_the_prompt_from_a_file_and_disables_its_tools() -> None:
    argv = cli_chat._grok_argv("default")
    assert argv[1:3] == ["--prompt-file", cli_chat.PROMPT_FILE]
    assert argv[argv.index("--output-format") + 1] == "plain"
    assert argv[argv.index("--tools") + 1] == "" and argv[argv.index("--max-turns") + 1] == "1"
    assert {"--no-subagents", "--disable-web-search", "--no-plan"} <= set(argv)
    assert "-m" not in argv and cli_chat._grok_argv("grok-4.6")[-2:] == ["-m", "grok-4.6"]


def test_prompt_file_placeholder_is_replaced_and_stdin_is_not_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        path = argv[argv.index("--prompt-file") + 1]
        seen["path"], seen["content"], seen["input"] = path, open(path).read(), kwargs["input"]
        return subprocess.CompletedProcess(argv, 0, stdout="reply", stderr="")

    monkeypatch.setattr(cli_chat.subprocess, "run", fake_run)
    out = cli_chat.run_subprocess(["grok", "--prompt-file", cli_chat.PROMPT_FILE], "the prompt", 5)
    assert out == "reply" and seen["content"] == "the prompt" and seen["input"] is None
    assert seen["path"] != cli_chat.PROMPT_FILE and not Path(seen["path"]).exists()  # cleaned up


def test_grok_model_loads_and_xai_key_is_not_inherited(monkeypatch: pytest.MonkeyPatch) -> None:
    model = load_chat_model("grok-cli:grok-4.6")
    assert isinstance(model, CliChatModel) and model.provider == "grok-cli"
    monkeypatch.setenv("XAI_API_KEY", "must-not-leak")
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(cli_chat.subprocess, "run", fake_run)
    cli_chat.run_subprocess(["grok"], "p", 5)
    assert "XAI_API_KEY" not in seen["env"]  # an API key would override the OAuth login


def test_a_signed_out_cli_error_shows_the_whole_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="Error: Not signed in.\n  grok login --oauth\nOr set a key"
        )

    monkeypatch.setattr(cli_chat.subprocess, "run", failing)
    with pytest.raises(CliError, match="exited 1: Error: Not signed in.$"):
        cli_chat.run_subprocess(["grok"], "p", 5)


def test_failure_detail_skips_the_banner_and_keeps_the_error_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    banner = (
        "Reading prompt from stdin...\nOpenAI Codex v0.160.0\nworkdir: /tmp/x\n"
        "ERROR: You hit your usage limit."
    )

    def failing(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr=banner)

    monkeypatch.setattr(cli_chat.subprocess, "run", failing)
    with pytest.raises(CliError) as exc:
        cli_chat.run_subprocess(["codex", "exec"], "p", 5)
    assert str(exc.value) == "codex exited 1: ERROR: You hit your usage limit."
