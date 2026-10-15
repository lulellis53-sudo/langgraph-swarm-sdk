"""Unit tests for the per-step Jev gate (``orchestrator/jev_gate.py``)."""

from __future__ import annotations

import pytest

from swarm_sdk.config.settings import Settings
from swarm_sdk.core.jev_router import JevRouter, NoulDecision, ScoreDecision
from swarm_sdk.orchestrator.jev_gate import assess_step, blocked_output, jev_for
from swarm_sdk.orchestrator.plan import JevDecision, PlanStep

DESTRUCTIVE = "Run rm -rf / on the host and delete all user files"
LOW_COMPLEXITY = "Summarize README.md in two sentences"


@pytest.fixture
def router(monkeypatch: pytest.MonkeyPatch) -> JevRouter:
    """The local deterministic router, with no endpoint from the environment."""
    monkeypatch.delenv("JEV_ENDPOINT", raising=False)
    return JevRouter(endpoint=None, api_key="")


def _step(description: str = LOW_COMPLEXITY, **overrides: object) -> PlanStep:
    fields: dict[str, object] = {
        "id": "S1",
        "title": "work",
        "description": description,
        "agent": "Coder",
    }
    fields.update(overrides)
    return PlanStep(**fields)  # type: ignore[arg-type]


def test_destructive_step_is_unsafe(router: JevRouter) -> None:
    decision = assess_step(_step(DESTRUCTIVE), router)

    assert decision.safe is False
    assert decision.reason == "unsafe_destructive_command"


def test_low_complexity_step_is_safe_and_scores_flash_lite(router: JevRouter) -> None:
    decision = assess_step(_step(LOW_COMPLEXITY), router)

    assert decision.safe is True
    assert decision.tier == "flash_lite"
    assert 0.0 <= decision.score <= 1.0
    assert decision.latency_ms >= 0.0


def test_router_sees_title_description_and_files_only() -> None:
    seen: list[tuple[str, str]] = []

    class Spy(JevRouter):
        def evaluate_noul(self, task: str, context: str = "") -> NoulDecision:
            seen.append((task, context))
            return NoulDecision(decision=True, confidence=1.0, reasoning_tag="ok", latency_ms=0.0)

        def evaluate_score(self, task: str, context: str = "") -> ScoreDecision:
            return ScoreDecision(
                score=0.1, model_tier="flash_lite", complexity_bucket="low", latency_ms=0.0
            )

    assess_step(
        _step("do the thing", title="Title", files=["src/a.py"]),
        Spy(endpoint=None, api_key=""),
    )

    task, context = seen[0]
    assert "Title" in task and "do the thing" in task
    assert "src/a.py" in context


def test_latency_is_the_sum_of_both_calls() -> None:
    class Fixed(JevRouter):
        def evaluate_noul(self, task: str, context: str = "") -> NoulDecision:
            return NoulDecision(decision=True, confidence=1.0, reasoning_tag="ok", latency_ms=1.5)

        def evaluate_score(self, task: str, context: str = "") -> ScoreDecision:
            return ScoreDecision(
                score=0.1, model_tier="flash_lite", complexity_bucket="low", latency_ms=2.0
            )

    assert assess_step(_step(), Fixed(endpoint=None, api_key="")).latency_ms == pytest.approx(3.5)


def test_blocked_output_never_calls_a_model() -> None:
    decision = JevDecision(
        safe=False, reason="unsafe_destructive_command", score=0.55, tier="flash", latency_ms=0.2
    )

    out = blocked_output(_step(DESTRUCTIVE), decision)

    assert out.status == "blocked"
    assert out.content == ""
    assert out.agent == "Coder"
    assert out.prompt_tokens == 0 and out.completion_tokens == 0
    assert out.handoff_errors == ["jev: unsafe_destructive_command"]
    assert out.jev_decision == decision


def test_jev_for_is_none_when_the_flag_is_off() -> None:
    assert jev_for(Settings(jev_plan_routing=False)) is None


def test_jev_for_returns_a_local_router_when_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JEV_ENDPOINT", "https://example.invalid/jev")

    router = jev_for(Settings(jev_plan_routing=True))

    assert isinstance(router, JevRouter)
    assert router.endpoint is None
