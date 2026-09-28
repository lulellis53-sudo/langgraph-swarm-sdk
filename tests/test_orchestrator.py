"""Orchestration engine: plans, waves, workers, spawn, and LangGraph execution."""

import time
from pathlib import Path

import pytest

from fakes import Script, ScriptedModel, answer
from swarm_sdk.agents.manifest import AgentManifest
from swarm_sdk.orchestrator import Plan, PlanStep, make_factory, run_plan, spawn
from swarm_sdk.orchestrator.graph import build_graph
from swarm_sdk.orchestrator.worker import WorkerAgent, role_contract


def manifest(name: str = "Coder", **overrides: object) -> AgentManifest:
    data = {
        "name": name,
        "role": f"role of {name}",
        "model": "openai:gpt-4o",
        "token_budget": {"max_prompt": 512, "max_completion": 128},
    }
    data.update(overrides)
    return AgentManifest.model_validate(data)


def test_plan_waves_parallel_frontier() -> None:
    plan = Plan(
        steps=[
            PlanStep(id="S1", title="a", description="a", agent="Coder"),
            PlanStep(id="S2", title="b", description="b", agent="Tester"),
            PlanStep(id="S3", title="c", description="c", agent="Coder", depends_on=["S1", "S2"]),
        ]
    )
    waves = plan.waves()
    assert [sorted(s.id for s in wave) for wave in waves] == [["S1", "S2"], ["S3"]]


def test_plan_cycle_rejected() -> None:
    plan = Plan(
        steps=[
            PlanStep(id="S1", title="a", description="a", agent="Coder", depends_on=["S2"]),
            PlanStep(id="S2", title="b", description="b", agent="Coder", depends_on=["S1"]),
        ]
    )
    with pytest.raises(ValueError):
        plan.waves()


def test_manifest_new_fields() -> None:
    m = manifest(effort="high", api_key_env="SWARM_CODER_API_KEY")
    assert m.effort == "high"
    assert m.api_key_env == "SWARM_CODER_API_KEY"
    with pytest.raises(Exception):
        manifest(effort="extreme")


def test_role_contract_reads_agents_md() -> None:
    text = role_contract(str(Path("Agents").resolve()), "Orchestrator")
    assert "traffic controller" in text


def test_role_contract_missing_is_empty(tmp_path: Path) -> None:
    assert role_contract(str(tmp_path), "Nobody") == ""


async def test_worker_run_uses_role_and_counts_tokens(tmp_path: Path) -> None:
    script = Script([answer("done-ok")])
    model = ScriptedModel(script=script)
    agent = WorkerAgent(manifest("Coder"), agents_root=str(tmp_path), model_override=model)
    out = await agent.run("S1", "do the thing", {"S0": "prior output"})
    assert out.content == "done-ok"
    assert out.agent == "Coder"
    assert out.prompt_tokens > 0
    assert out.completion_tokens > 0
    # user prompt carries the declared dep output, not a transcript
    assert "prior output" in script.seen[-1]


async def test_spawn_validates_and_falls_back() -> None:
    manifests = {"Orchestrator": manifest("Orchestrator"), "Coder": manifest("Coder")}
    good_json = '{"steps": [{"id": "S1", "title": "t", "description": "d", "agent": "Coder"}]}'
    good = Script([answer(good_json)])
    plan = await spawn("goal", manifests, model_override=ScriptedModel(script=good))
    assert [s.id for s in plan.steps] == ["S1"]
    assert plan.steps[0].agent == "Coder"

    bad = Script([answer("no json here"), answer("still not json")])
    plan = await spawn("goal", manifests, model_override=ScriptedModel(script=bad))
    assert len(plan.steps) == 1  # fallback plan

    unknown_agent = Script(
        [answer('{"steps": [{"id": "S1", "title": "t", "description": "d", "agent": "Ghost"}]}')],
    )
    plan = await spawn("goal", manifests, model_override=ScriptedModel(script=unknown_agent))
    assert plan.steps[0].agent in manifests  # rejected, fell back


async def test_run_plan_executes_waves_in_parallel() -> None:
    manifests = {"Coder": manifest("Coder"), "Tester": manifest("Tester")}
    # one scripted response per step; both wave-1 steps share the scripted model
    script = Script([answer("ok-1"), answer("ok-2"), answer("merged")])
    model = ScriptedModel(script=script)
    plan = Plan(
        steps=[
            PlanStep(id="S1", title="a", description="a", agent="Coder"),
            PlanStep(id="S2", title="b", description="b", agent="Tester"),
            PlanStep(
                id="S3",
                title="c",
                description="c",
                agent="Coder",
                depends_on=["S1", "S2"],
                inputs=["S1", "S2"],
            ),
        ]
    )
    factory = make_factory(manifests, model_override=model)
    started = time.perf_counter()
    result = await run_plan(plan, factory)
    wall = time.perf_counter() - started

    assert set(result.outputs) == {"S1", "S2", "S3"}
    assert result.outputs["S3"].content == "merged"
    assert result.usage.llm_calls == 3
    assert result.usage.prompt_tokens > 0
    assert wall < 5  # scripted; guards against serialization bugs


def test_build_graph_compiles() -> None:
    plan = Plan(steps=[PlanStep(id="S1", title="a", description="a", agent="Coder")])
    graph = build_graph(plan, make_factory({"Coder": manifest("Coder")}))
    compiled = graph.compile()
    assert compiled is not None
