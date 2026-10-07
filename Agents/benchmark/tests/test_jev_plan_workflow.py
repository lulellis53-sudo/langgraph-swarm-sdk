"""Per-step Jev routing in the plan engine: safety gate, advisory tier, concurrency."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from swarm_sdk.core.jev_router import JevRouter
from swarm_sdk.orchestrator import Plan, PlanStep, run_plan
from swarm_sdk.orchestrator.plan import StepOutput

DESTRUCTIVE = "Run rm -rf / on the host and delete all user files"
LOW_COMPLEXITY = "Summarize README.md in two sentences"


class _Probe:
    """A worker factory that records which steps reached a worker and how many overlapped."""

    def __init__(self, delay_s: float = 0.0) -> None:
        self.built: list[str] = []
        self.delay_s = delay_s
        self.active = 0
        self.peak = 0

    def __call__(self, step: PlanStep) -> MagicMock:
        self.built.append(step.id)
        worker = MagicMock()

        async def run(step_id, description, inputs, files=(), task="") -> StepOutput:
            self.active += 1
            self.peak = max(self.peak, self.active)
            await asyncio.sleep(self.delay_s)
            self.active -= 1
            return StepOutput(
                step_id=step_id,
                agent=step.agent,
                content=f"done {step_id}",
                prompt_tokens=10,
                completion_tokens=5,
            )

        worker.run = run
        return worker


def _step(step_id: str, description: str = LOW_COMPLEXITY, **overrides: object) -> PlanStep:
    fields: dict[str, object] = {
        "id": step_id,
        "title": step_id.lower(),
        "description": description,
        "agent": "Researcher",
    }
    fields.update(overrides)
    return PlanStep(**fields)  # type: ignore[arg-type]


async def test_flag_off_never_touches_the_router(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: JevRouter, *args: object, **kwargs: object) -> None:
        raise AssertionError("JevRouter must not be called when Jev routing is off")

    monkeypatch.setattr(JevRouter, "evaluate_noul", boom)
    monkeypatch.setattr(JevRouter, "evaluate_score", boom)
    probe = _Probe()

    result = await run_plan(Plan(steps=[_step("S1"), _step("S2", depends_on=["S1"])]), probe)

    assert probe.built == ["S1", "S2"]
    assert all(out.jev_decision is None for out in result.outputs.values())


async def test_every_executed_step_records_a_decision(local_jev: JevRouter) -> None:
    plan = Plan(steps=[_step("S1"), _step("S2", depends_on=["S1"]), _step("S3", depends_on=["S2"])])

    result = await run_plan(plan, _Probe(), jev=local_jev)

    assert set(result.outputs) == {"S1", "S2", "S3"}
    assert all(
        out.jev_decision is not None and out.jev_decision.safe for out in result.outputs.values()
    )


async def test_unsafe_step_is_blocked_and_never_reaches_a_worker(local_jev: JevRouter) -> None:
    probe = _Probe()

    result = await run_plan(Plan(steps=[_step("S1", DESTRUCTIVE)]), probe, jev=local_jev)

    out = result.outputs["S1"]
    assert out.status == "blocked"
    assert out.handoff_errors == ["jev: unsafe_destructive_command"]
    assert probe.built == []
    assert result.usage.llm_calls == 0
    assert result.usage.prompt_tokens == 0


async def test_dependents_of_a_blocked_step_are_blocked_too(local_jev: JevRouter) -> None:
    probe = _Probe()
    plan = Plan(
        steps=[
            _step("S1", DESTRUCTIVE),
            _step("S2", depends_on=["S1"]),
            _step("S3", depends_on=["S2"]),
        ]
    )

    result = await run_plan(plan, probe, jev=local_jev)

    assert [result.outputs[s].status for s in ("S1", "S2", "S3")] == ["blocked"] * 3
    assert result.outputs["S2"].handoff_errors == ["jev: dependency S1 blocked"]
    assert result.outputs["S3"].handoff_errors == ["jev: dependency S2 blocked"]
    assert probe.built == []


async def test_a_blocked_step_does_not_stop_independent_steps(local_jev: JevRouter) -> None:
    probe = _Probe()

    result = await run_plan(
        Plan(steps=[_step("S1", DESTRUCTIVE), _step("S2")]), probe, jev=local_jev
    )

    assert result.outputs["S1"].status == "blocked"
    assert result.outputs["S2"].status == "ok"
    assert probe.built == ["S2"]


async def test_score_tier_is_recorded_but_does_not_change_the_worker(
    local_jev: JevRouter,
) -> None:
    probe = _Probe()
    step = _step("S1", LOW_COMPLEXITY)

    result = await run_plan(Plan(steps=[step]), probe, jev=local_jev)

    decision = result.outputs["S1"].jev_decision
    assert decision is not None and decision.tier == "flash_lite"
    assert probe.built == ["S1"]
    assert result.outputs["S1"].agent == "Researcher"


async def test_independent_steps_still_run_concurrently_with_jev(local_jev: JevRouter) -> None:
    probe = _Probe(delay_s=0.05)

    await run_plan(Plan(steps=[_step("S1"), _step("S2")]), probe, jev=local_jev, max_concurrency=2)

    assert probe.peak == 2


async def test_a_failing_router_runs_the_step_as_if_jev_were_off() -> None:
    class Broken(JevRouter):
        def evaluate_noul(self, task: str, context: str = ""):  # noqa: ANN201
            raise RuntimeError("router down")

    probe = _Probe()

    result = await run_plan(Plan(steps=[_step("S1")]), probe, jev=Broken(endpoint=None, api_key=""))

    assert result.outputs["S1"].status == "ok"
    assert result.outputs["S1"].jev_decision is None
    assert probe.built == ["S1"]


async def test_per_step_decision_latency_is_small(local_jev: JevRouter) -> None:
    result = await run_plan(Plan(steps=[_step("S1")]), _Probe(), jev=local_jev)

    decision = result.outputs["S1"].jev_decision
    assert decision is not None
    # The contract is 10 ms locally; 50 ms keeps the test stable on a busy machine.
    assert decision.latency_ms < 50.0
