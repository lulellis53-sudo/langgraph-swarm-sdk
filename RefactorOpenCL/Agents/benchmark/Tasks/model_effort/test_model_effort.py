"""Check model-effort benchmark scoring and timing without provider calls."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from benchmark import model_effort as benchmark
from benchmark.model_effort import (
    BenchmarkCase,
    ModelReply,
    _codex,
    aggregate,
    load_cases,
    load_routes,
    main,
    run_case,
    run_suite,
)


def test_run_case_excludes_only_model_wait() -> None:
    ticks = iter([0.0, 0.002, 0.102, 0.105])
    case = BenchmarkCase("c1", "classification", "Return yes", "yes")

    def invoke(_model: str, _effort: str, _prompt: str) -> ModelReply:
        return ModelReply("YES", 3, 2)

    row = run_case(case, "openai:gpt-4o-mini", "low", invoke, clock=lambda: next(ticks))
    assert row["score"] == 1.0
    assert row["input_tokens"] == 3
    assert row["output_tokens"] == 2
    assert row["total_tokens"] == 5
    assert round(row["model_ms"], 3) == 100.0
    assert round(row["overhead_ms"], 3) == 5.0
    assert round(row["wall_ms"], 3) == 105.0


def test_aggregate_groups_by_type_model_and_effort() -> None:
    cases = [
        BenchmarkCase("a", "classification", "one", "yes"),
        BenchmarkCase("b", "classification", "two", "yes"),
        BenchmarkCase("c", "extraction", "three", "42"),
    ]
    answers = {"one": "yes", "two": "no", "three": "42"}

    def invoke(_model: str, _effort: str, prompt: str) -> ModelReply:
        return ModelReply(answers[prompt], 4, 2)

    rows = run_suite(cases, [("model-a", "low"), ("model-b", "high")], invoke)
    groups = aggregate(rows)
    assert len(rows) == 6
    assert len(groups) == 4
    low_class = next(
        item for item in groups if item["task_type"] == "classification" and item["effort"] == "low"
    )
    assert low_class["mean_score"] == 0.5
    assert low_class["total_tokens"] == 12
    assert low_class["average_overhead_ms"] >= 0


def test_missing_usage_is_marked_unreported() -> None:
    case = BenchmarkCase("c1", "extraction", "Return 42", "42")
    row = run_case(case, "model-a", "low", lambda *_: ModelReply("42"))
    assert row["total_tokens"] is None
    assert row["token_source"] == "unreported"


def test_predefined_cases_cover_task_types_and_registry_efforts() -> None:
    assert {case.task_type for case in load_cases()} == {
        "classification",
        "extraction",
        "arithmetic",
    }
    routes = load_routes()
    assert routes
    assert all(model and effort in {"low", "medium", "high"} for model, effort in routes)


def test_scripted_cli_report_is_grouped(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--model", "openai:gpt-4o-mini", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "scripted"
    assert len(report["cases"]) == 6
    assert len(report["groups"]) == 3
    assert all(group["mean_score"] == 1.0 for group in report["groups"])
    assert all(row["token_source"] == "estimated" for row in report["cases"])


def test_codex_cli_agent_uses_profile_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[:4] == ["codex", "exec", "-p", "benchmark"]
        assert "model_reasoning_effort=medium" in command
        assert command[command.index("-s") + 1] == "read-only"
        assert kwargs["input"] == "Reply 42"
        Path(command[command.index("-o") + 1]).write_text("42", encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            0,
            '{"type":"turn.completed","usage":{"input_tokens":7,"output_tokens":2}}\n',
            "",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    reply = _codex("benchmark")("openai:gpt-6-luna", "medium", "Reply 42")
    assert reply == ModelReply("42", 7, 2, "codex")


def test_codex_route_cannot_use_api_provider_mode() -> None:
    with pytest.raises(SystemExit, match="2"):
        main(["--live", "--model", "openai:gpt-6-luna"])


def test_auto_selects_low_effort_credential_route_before_codex() -> None:
    entries = [
        {
            "name": "anthropic:large",
            "provider": "anthropic",
            "effort": "medium",
            "priority": 5,
            "api_key_env": "ANTHROPIC_API_KEY",
        },
        {
            "name": "openai:small",
            "provider": "openai",
            "effort": "low",
            "priority": 70,
            "api_key_env": "OPENAI_API_KEY",
        },
        {
            "name": "openai:codex",
            "provider": "codex",
            "effort": "medium",
            "priority": 20,
            "api_key_env": "CODEX_OAUTH_TOKEN",
        },
    ]
    route = benchmark.select_auto_route(
        entries,
        credential_available=lambda name: name == "OPENAI_API_KEY",
        codex_profile="Comand",
    )
    assert (route.model, route.effort, route.mode) == ("openai:small", "low", "live")


def test_auto_falls_back_to_codex_without_api_key() -> None:
    entries = [
        {
            "name": "openai:small",
            "provider": "openai",
            "effort": "low",
            "priority": 70,
            "api_key_env": "OPENAI_API_KEY",
        },
        {
            "name": "openai:codex",
            "provider": "codex",
            "effort": "medium",
            "priority": 20,
            "api_key_env": "CODEX_OAUTH_TOKEN",
        },
    ]
    route = benchmark.select_auto_route(
        entries, credential_available=lambda _: False, codex_profile="Comand"
    )
    assert (route.model, route.mode) == ("openai:codex", "codex")


def test_auto_accepts_native_mistral_route() -> None:
    route = benchmark.select_auto_route(
        [
            {
                "name": "mistral:ministral-3-8b-latest",
                "provider": "mistral-2",
                "effort": "low",
                "priority": 2,
                "api_key_env": "MISTRAL_API_KEY",
            }
        ],
        credential_available=lambda name: name == "MISTRAL_API_KEY",
        codex_profile=None,
    )
    assert route.model == "mistral:ministral-3-8b-latest"


@pytest.mark.parametrize(
    ("model", "provider", "key"),
    [
        ("groq:openai/gpt-oss-20b", "groq-2", "GROQ_API_KEY_2"),
        ("sambanova:Meta-Llama-3.3-70B-Instruct", "sambanova", "SAMBANOVA_API_KEY"),
        ("fireworks:accounts/fireworks/models/kimi-k2.7", "fireworks", "FIREWORKS_API_KEY"),
        ("openrouter:z-ai/glm-5.3-flash", "openrouter", "OPENROUTER_API_KEY"),
        ("mistral:ministral-3-8b-latest", "mistral-2", "MISTRAL_API_KEY_2"),
        ("cohere:command-r7b", "cohere-2", "COHERE_API_KEY_2"),
    ],
)
def test_auto_accepts_requested_provider(model: str, provider: str, key: str) -> None:
    route = benchmark.select_auto_route(
        [{"name": model, "provider": provider, "effort": "low", "priority": 1, "api_key_env": key}],
        credential_available=lambda name: name == key,
        codex_profile=None,
    )
    assert route.model == model


def test_live_hosted_route_does_not_require_optional_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from swarm_sdk import vault
    from swarm_sdk.models import chat

    seen: list[str] = []

    def fake_load(names: list[str]) -> list[str]:
        seen.extend(names)
        return [name for name in names if name != "OPENROUTER_API_KEY"]

    monkeypatch.setattr(vault, "load_into_env", fake_load)
    monkeypatch.setattr(chat, "load_chat_model", lambda _: object())
    benchmark._live(["openrouter:z-ai/glm-5.3-flash"])
    assert seen == ["OPENROUTER_API_KEY"]


def test_auto_covers_types_then_stops_before_projected_budget() -> None:
    cases = [
        BenchmarkCase("a1", "arithmetic", "a1", "ok"),
        BenchmarkCase("a2", "arithmetic", "a2", "ok"),
        BenchmarkCase("c1", "classification", "c1", "ok"),
        BenchmarkCase("c2", "classification", "c2", "ok"),
        BenchmarkCase("e1", "extraction", "e1", "ok"),
        BenchmarkCase("e2", "extraction", "e2", "ok"),
    ]
    report = benchmark.run_autonomous(
        cases,
        ("openai:codex", "medium"),
        lambda *_: ModelReply("ok", 12, 2, "codex"),
        max_total_tokens=50,
    )
    assert {row["task_type"] for row in report["cases"]} == {
        "arithmetic",
        "classification",
        "extraction",
    }
    assert len(report["cases"]) == 3
    assert report["complete"] is False
    assert report["stopped_reason"] == "projected_token_budget"
    assert report["reported_tokens"] == 42


def test_auto_cli_runs_eligible_agent_and_reports_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "Comand.config.toml").write_text('model = "gpt-6-sol"\n')
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(
        benchmark, "_codex", lambda _: lambda *_args: ModelReply("42", 4, 1, "codex")
    )
    assert (
        benchmark.main(
            [
                "--auto",
                "--model",
                "openai:gpt-6-luna",
                "--max-total-tokens",
                "50",
                "--json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "auto"
    assert report["selected_model"] == "openai:gpt-6-luna"
    assert report["expected_cases"] == 6
    assert report["complete"] is True
    assert len(report["cases"]) == 6


def test_auto_provider_error_returns_redacted_partial_report() -> None:
    def failing_invoke(*_args: str) -> ModelReply:
        raise RuntimeError("secret-token-in-provider-error")

    report = benchmark.run_autonomous(
        [BenchmarkCase("a", "arithmetic", "prompt", "42")],
        ("openai:small", "low"),
        failing_invoke,
        max_total_tokens=50,
    )
    assert report["complete"] is False
    assert report["stopped_reason"] == "agent_error"
    assert report["error_type"] == "RuntimeError"
    assert "secret-token" not in json.dumps(report)


def run() -> None:
    """Entry point for ``python -m benchmark.run --task model_effort``."""
    main([])
