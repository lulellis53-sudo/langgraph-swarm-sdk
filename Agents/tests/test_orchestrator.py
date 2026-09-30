"""Orchestration engine: plans, waves, workers, spawn, and LangGraph execution."""

from __future__ import annotations

import time
from pathlib import Path

import hypothesis.strategies as st
import pytest
from hypothesis import assume, given, settings
from pydantic import ValidationError
from tests.fakes import Script, ScriptedModel, answer

from swarm_sdk.agents.manifest import AgentManifest
from swarm_sdk.orchestrator import Plan, PlanStep, make_factory, run_plan, spawn
from swarm_sdk.orchestrator.graph import build_graph
from swarm_sdk.orchestrator.plan import normalize_claimed_file
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


def _chain_plan(n: int) -> Plan:
    """S1 ← S2 ← … ← Sn (each depends on the previous)."""
    steps = [
        PlanStep(
            id=f"S{i}",
            title=f"t{i}",
            description=f"d{i}",
            agent="Coder",
            depends_on=[] if i == 1 else [f"S{i - 1}"],
        )
        for i in range(1, n + 1)
    ]
    return Plan(steps=steps)


@st.composite
def dag_plans(draw: st.DrawFn) -> Plan:
    """Generate a small DAG of unique step ids with edges only to earlier ids."""
    n = draw(st.integers(min_value=1, max_value=8))
    ids = [f"S{i}" for i in range(1, n + 1)]
    steps: list[PlanStep] = []
    for i, step_id in enumerate(ids):
        prior = ids[:i]
        deps = (
            draw(st.lists(st.sampled_from(prior), max_size=min(3, len(prior)), unique=True))
            if prior
            else []
        )
        steps.append(
            PlanStep(id=step_id, title=step_id, description=step_id, agent="Coder", depends_on=deps)
        )
    return Plan(steps=steps)


@given(n=st.integers(min_value=1, max_value=12))
@settings(max_examples=30)
def test_chain_plan_has_one_step_per_wave(n: int) -> None:
    waves = _chain_plan(n).waves()
    assert len(waves) == n
    assert [step.id for wave in waves for step in wave] == [f"S{i}" for i in range(1, n + 1)]


@given(plan=dag_plans())
@settings(max_examples=40)
def test_dag_waves_cover_each_step_once(plan: Plan) -> None:
    waves = plan.waves()
    seen = [step.id for wave in waves for step in wave]
    assert sorted(seen) == sorted(s.id for s in plan.steps)
    assert len(seen) == len(set(seen))
    completed: set[str] = set()
    for wave in waves:
        for step in wave:
            assert set(step.depends_on) <= completed
        completed.update(step.id for step in wave)


@given(plan=dag_plans())
@settings(max_examples=20)
def test_cycle_via_self_edge_rejected(plan: Plan) -> None:
    assume(plan.steps)
    broken = Plan(
        steps=[
            PlanStep(
                id=s.id,
                title=s.title,
                description=s.description,
                agent=s.agent,
                task=s.task,
                files=s.files,
                depends_on=s.depends_on if s.id != plan.steps[0].id else [s.id],
            )
            for s in plan.steps
        ]
    )
    with pytest.raises(ValueError):
        broken.waves()


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


def test_normalize_claimed_file() -> None:
    assert normalize_claimed_file(r"src\foo.py") == "src/foo.py"
    assert normalize_claimed_file("./src/foo.py") == "src/foo.py"
    with pytest.raises(ValueError):
        normalize_claimed_file("/abs/foo.py")
    with pytest.raises(ValueError):
        normalize_claimed_file("../secret.py")
    with pytest.raises(ValueError):
        normalize_claimed_file("  ")


def test_plan_step_files_normalized_and_unique() -> None:
    step = PlanStep(
        id="S1",
        title="t",
        description="d",
        agent="Coder",
        files=["src/a.py", r"src\a.py", "./src/b.py"],
    )
    assert step.files == ["src/a.py", "src/b.py"]
    with pytest.raises(ValidationError):
        PlanStep(id="S1", title="t", description="d", agent="Coder", files=["../x.py"])


def test_file_partition_rejects_overlap() -> None:
    plan = Plan(
        steps=[
            PlanStep(id="S1", title="a", description="a", agent="Coder", files=["src/a.py"]),
            PlanStep(id="S2", title="b", description="b", agent="Coder", files=["src/a.py"]),
        ]
    )
    with pytest.raises(ValueError, match="both claim"):
        plan.assert_file_partition()


def test_file_partition_rejects_unscoped_parallel_coders() -> None:
    plan = Plan(
        steps=[
            PlanStep(id="S1", title="a", description="a", agent="Coder"),
            PlanStep(id="S2", title="b", description="b", agent="Coder"),
        ]
    )
    with pytest.raises(ValueError, match="unscoped"):
        plan.assert_file_partition()


def test_file_partition_allows_disjoint_coders() -> None:
    plan = Plan(
        steps=[
            PlanStep(
                id="S1",
                title="a",
                description="a",
                agent="Coder",
                task="implement_in_files",
                files=["src/a.py", "tests/test_a.py"],
            ),
            PlanStep(
                id="S2",
                title="b",
                description="b",
                agent="Coder",
                task="implement_in_files",
                files=["src/b.py", "tests/test_b.py"],
            ),
        ]
    )
    plan.assert_file_partition()
    assert [sorted(s.id for s in wave) for wave in plan.waves()] == [["S1", "S2"]]


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
    assert "prior output" in script.seen[-1]


async def test_worker_prompt_includes_task_and_files(tmp_path: Path) -> None:
    script = Script([answer("done-ok")])
    model = ScriptedModel(script=script)
    agent = WorkerAgent(manifest("Coder"), agents_root=str(tmp_path), model_override=model)
    await agent.run(
        "S1",
        "do the thing",
        {},
        files=["src/a.py"],
        task="implement_in_files",
    )
    seen = script.seen[-1]
    assert "task: implement_in_files" in seen
    assert "- src/a.py" in seen


async def test_spawn_validates_and_falls_back() -> None:
    manifests = {"Orchestrator": manifest("Orchestrator"), "Coder": manifest("Coder")}
    good_json = '{"steps": [{"id": "S1", "title": "t", "description": "d", "agent": "Coder"}]}'
    good = Script([answer(good_json)])
    plan = await spawn("goal", manifests, model_override=ScriptedModel(script=good))
    assert [s.id for s in plan.steps] == ["S1"]
    assert plan.steps[0].agent == "Coder"

    bad = Script([answer("no json here"), answer("still not json")])
    plan = await spawn("goal", manifests, model_override=ScriptedModel(script=bad))
    assert len(plan.steps) == 1

    unknown_agent = Script(
        [answer('{"steps": [{"id": "S1", "title": "t", "description": "d", "agent": "Ghost"}]}')],
    )
    plan = await spawn("goal", manifests, model_override=ScriptedModel(script=unknown_agent))
    assert plan.steps[0].agent in manifests


async def test_spawn_rejects_overlapping_coder_files() -> None:
    manifests = {
        "Orchestrator": manifest("Orchestrator"),
        "Coder": manifest(
            "Coder",
            tasks=[{"id": "implement_in_files", "description": "scoped edit"}],
        ),
    }
    overlap = (
        '{"steps": ['
        '{"id": "S1", "title": "a", "description": "a", "agent": "Coder",'
        ' "task": "implement_in_files", "files": ["src/a.py"]},'
        '{"id": "S2", "title": "b", "description": "b", "agent": "Coder",'
        ' "task": "implement_in_files", "files": ["src/a.py"]}'
        "]}"
    )
    script = Script([answer(overlap), answer(overlap)])
    plan = await spawn("goal", manifests, model_override=ScriptedModel(script=script))
    assert len(plan.steps) == 1


async def test_spawn_accepts_disjoint_coder_files() -> None:
    manifests = {
        "Orchestrator": manifest("Orchestrator"),
        "Coder": manifest(
            "Coder",
            tasks=[{"id": "implement_in_files", "description": "scoped edit"}],
        ),
    }
    good = (
        '{"steps": ['
        '{"id": "S1", "title": "a", "description": "a", "agent": "Coder",'
        ' "task": "implement_in_files", "files": ["src/a.py"]},'
        '{"id": "S2", "title": "b", "description": "b", "agent": "Coder",'
        ' "task": "implement_in_files", "files": ["src/b.py"]}'
        "]}"
    )
    scripted = ScriptedModel(script=Script([answer(good)]))
    plan = await spawn("goal", manifests, model_override=scripted)
    assert [s.id for s in plan.steps] == ["S1", "S2"]
    assert plan.steps[0].files == ["src/a.py"]
    assert plan.steps[0].task == "implement_in_files"


async def test_run_plan_executes_waves_in_parallel() -> None:
    manifests = {"Coder": manifest("Coder"), "Tester": manifest("Tester")}
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
    assert wall < 5


async def test_run_plan_parallel_coders_with_disjoint_files() -> None:
    manifests = {"Coder": manifest("Coder")}
    script = Script([answer("ok-a"), answer("ok-b")])
    model = ScriptedModel(script=script)
    plan = Plan(
        steps=[
            PlanStep(
                id="S1",
                title="a",
                description="a",
                agent="Coder",
                files=["src/a.py"],
                task="implement_in_files",
            ),
            PlanStep(
                id="S2",
                title="b",
                description="b",
                agent="Coder",
                files=["src/b.py"],
                task="implement_in_files",
            ),
        ]
    )
    result = await run_plan(plan, make_factory(manifests, model_override=model), max_concurrency=1)
    assert set(result.outputs) == {"S1", "S2"}
    assert result.usage.llm_calls == 2


def test_build_graph_compiles() -> None:
    plan = Plan(steps=[PlanStep(id="S1", title="a", description="a", agent="Coder")])
    graph = build_graph(plan, make_factory({"Coder": manifest("Coder")}))
    compiled = graph.compile()
    assert compiled is not None
