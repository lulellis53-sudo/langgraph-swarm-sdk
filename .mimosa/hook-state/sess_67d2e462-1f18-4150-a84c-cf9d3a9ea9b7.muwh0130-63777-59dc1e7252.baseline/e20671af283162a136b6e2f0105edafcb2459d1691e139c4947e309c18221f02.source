"""Swarm coordination: wave synchronization, parallelism, efficiency, delegation."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict

from benchmark.tests.test_orchestrator import manifest
from swarm_sdk.orchestrator import Plan, PlanStep, make_factory, run_plan
from swarm_sdk.orchestrator.worker import role_contract
from swarm_sdk.retrieval.cache import SemanticCache
from swarm_sdk.retrieval.embeddings import HashEmbedder

DELAY_S = 0.2


class Probe:
    """Thread-safe record of every model call: timing, prompts, concurrency."""

    def __init__(self, delay: float = DELAY_S, fail_on: str = "") -> None:
        self.delay = delay
        self.fail_on = fail_on
        self.lock = threading.Lock()
        self.in_flight = 0
        self.peak = 0
        self.calls: list[dict[str, Any]] = []


class ProbeModel(BaseChatModel):
    """Chat model that sleeps, tracks peak concurrency, and echoes its step id."""

    probe: Probe
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "probe"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        system, user = str(messages[0].content), str(messages[-1].content)
        probe = self.probe
        with probe.lock:
            probe.in_flight += 1
            probe.peak = max(probe.peak, probe.in_flight)
        started = time.perf_counter()
        try:
            time.sleep(probe.delay)
            if probe.fail_on and probe.fail_on in user:
                raise RuntimeError(f"provider down for {probe.fail_on}")
        finally:
            with probe.lock:
                probe.in_flight -= 1
                probe.calls.append(
                    {
                        "system": system,
                        "user": user,
                        "start": started,
                        "end": time.perf_counter(),
                    }
                )
        head = user.splitlines()[0]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=f"out:{head}"))])


def _step(sid: str, agent: str = "Tester", **kw: Any) -> PlanStep:
    return PlanStep(id=sid, title=sid, description=f"do-{sid}", agent=agent, **kw)


def _call_for(probe: Probe, sid: str) -> dict[str, Any]:
    (call,) = [c for c in probe.calls if c["user"].startswith(f"do-{sid}")]
    return call


_BUDGET = {"max_prompt": 100_000, "max_completion": 128}  # real AGENTS.md contracts are large
MANIFESTS = {
    "Coder": manifest("Coder", token_budget=_BUDGET),
    "Tester": manifest("Tester", token_budget=_BUDGET),
}


async def test_independent_steps_run_concurrently() -> None:
    probe = Probe()
    plan = Plan(steps=[_step(f"S{i}") for i in range(1, 5)])
    started = time.perf_counter()
    result = await run_plan(
        plan, make_factory(MANIFESTS, model_override=ProbeModel(probe=probe)), max_concurrency=4
    )
    wall = time.perf_counter() - started

    assert set(result.outputs) == {"S1", "S2", "S3", "S4"}
    assert probe.peak == 4
    assert wall < 3 * DELAY_S  # serial would be 4 * DELAY_S


@pytest.mark.parametrize("cap", [1, 2, 3])
async def test_max_concurrency_caps_in_flight_steps(cap: int) -> None:
    probe = Probe(delay=0.05)
    plan = Plan(steps=[_step(f"S{i}") for i in range(1, 7)])
    await run_plan(
        plan, make_factory(MANIFESTS, model_override=ProbeModel(probe=probe)), max_concurrency=cap
    )
    assert probe.peak == cap
    assert len(probe.calls) == 6


async def test_dependent_step_waits_for_whole_wave() -> None:
    probe = Probe()
    plan = Plan(
        steps=[
            _step("S1"),
            _step("S2"),
            _step("S3", depends_on=["S1", "S2"], inputs=["S1", "S2"]),
        ]
    )
    await run_plan(plan, make_factory(MANIFESTS, model_override=ProbeModel(probe=probe)))

    barrier = max(_call_for(probe, "S1")["end"], _call_for(probe, "S2")["end"])
    assert _call_for(probe, "S3")["start"] >= barrier


async def test_step_receives_only_declared_inputs() -> None:
    probe = Probe(delay=0)
    plan = Plan(
        steps=[
            _step("S1"),
            _step("S2"),
            _step("S3", depends_on=["S1", "S2"], inputs=["S1"]),
        ]
    )
    await run_plan(plan, make_factory(MANIFESTS, model_override=ProbeModel(probe=probe)))

    prompt = _call_for(probe, "S3")["user"]
    assert "S1: out:do-S1" in prompt
    assert "out:do-S2" not in prompt


async def test_inputs_default_to_depends_on() -> None:
    probe = Probe(delay=0)
    plan = Plan(steps=[_step("S1"), _step("S2", depends_on=["S1"])])
    await run_plan(plan, make_factory(MANIFESTS, model_override=ProbeModel(probe=probe)))

    assert "S1: out:do-S1" in _call_for(probe, "S2")["user"]


async def test_cached_rerun_makes_no_llm_calls(tmp_path: Path) -> None:
    cache = SemanticCache(str(tmp_path / "c.db"), HashEmbedder(16))
    plan = Plan(steps=[_step("S1"), _step("S2", agent="Tester")])

    cold = Probe(delay=0)
    first = await run_plan(
        plan, make_factory(MANIFESTS, cache=cache, model_override=ProbeModel(probe=cold))
    )
    warm = Probe(delay=0)
    second = await run_plan(
        plan, make_factory(MANIFESTS, cache=cache, model_override=ProbeModel(probe=warm))
    )

    assert first.usage.llm_calls == 2 and first.usage.cached_calls == 0
    assert second.usage.llm_calls == 0 and second.usage.cached_calls == 2
    assert second.usage.prompt_tokens == 0
    assert warm.calls == []
    assert {k: v.content for k, v in second.outputs.items()} == {
        k: v.content for k, v in first.outputs.items()
    }


async def test_usage_totals_sum_step_tokens() -> None:
    probe = Probe(delay=0)
    plan = Plan(steps=[_step("S1"), _step("S2"), _step("S3", depends_on=["S1"])])
    result = await run_plan(plan, make_factory(MANIFESTS, model_override=ProbeModel(probe=probe)))

    assert result.usage.llm_calls == 3
    assert result.usage.prompt_tokens == sum(o.prompt_tokens for o in result.outputs.values())
    assert result.usage.completion_tokens == sum(
        o.completion_tokens for o in result.outputs.values()
    )
    assert result.usage.wall_s > 0


async def test_each_step_is_delegated_to_its_own_agent() -> None:
    probe = Probe(delay=0)
    plan = Plan(steps=[_step("S1", agent="Coder"), _step("S2", agent="Tester")])
    result = await run_plan(plan, make_factory(MANIFESTS, model_override=ProbeModel(probe=probe)))

    assert result.outputs["S1"].agent == "Coder"
    assert result.outputs["S2"].agent == "Tester"
    root = str(Path(__file__).resolve().parents[3] / "Agents")
    assert _call_for(probe, "S1")["system"].startswith(role_contract(root, "Coder")[:40])
    assert _call_for(probe, "S2")["system"].startswith(role_contract(root, "Tester")[:40])
    assert _call_for(probe, "S1")["system"] != _call_for(probe, "S2")["system"]


async def test_failed_step_aborts_plan_without_running_later_waves() -> None:
    probe = Probe(delay=0.05, fail_on="do-S2")
    plan = Plan(
        steps=[
            _step("S1"),
            _step("S2"),
            _step("S3", depends_on=["S1", "S2"]),
        ]
    )
    with pytest.raises(RuntimeError, match="provider down for do-S2"):
        await run_plan(plan, make_factory(MANIFESTS, model_override=ProbeModel(probe=probe)))

    assert all(not c["user"].startswith("do-S3") for c in probe.calls)
