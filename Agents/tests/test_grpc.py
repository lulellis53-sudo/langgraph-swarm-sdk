from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from tests.fakes import Script, ScriptedModel, answer

from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.pb import swarm_pb2
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.rerank import IdentityReranker


def test_grpc_run_and_recall(tmp_path: Path) -> None:
    from swarm_sdk.serving.grpc import SwarmServicer

    model = ScriptedModel(
        script=Script(
            [
                AIMessage(content='{"mode":"swarm","tasks":[]}'),
                answer("grpc-answer"),
            ]
        )
    )
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        memory_backend="opencl",
    )
    sdk = SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
    )
    servicer = SwarmServicer(sdk)
    response = servicer.Run(swarm_pb2.RunRequest(text="hello grpc", thread_id="g"), None)
    assert response.text == "grpc-answer"
    assert response.cached is False
    recalled = servicer.Recall(swarm_pb2.RecallRequest(query="hello grpc", top_k=2), None)
    assert recalled.hits
    assert "grpc-answer" in recalled.hits[0].text


def test_run_plan_without_plan_id_returns_pollable_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from swarm_sdk.orchestrator.plan import PlanResult, StepOutput, UsageTotals
    from swarm_sdk.serving import grpc as grpc_server
    from swarm_sdk.serving.grpc import SwarmServicer

    async def fake_run_plan(plan, factory, **_kwargs: object):  # noqa: ANN001, ARG001
        step = plan.steps[0]
        return PlanResult(
            outputs={
                step.id: StepOutput(
                    step_id=step.id,
                    agent=step.agent,
                    content="done",
                )
            },
            usage=UsageTotals(),
        )

    monkeypatch.setattr(grpc_server, "run_plan", fake_run_plan)
    grpc_server._PLANS.clear()
    grpc_server._RESULTS.clear()

    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        memory_backend="opencl",
    )
    sdk = SwarmSDK(
        settings,
        router_model=ScriptedModel(script=Script([])),
        specialist_model=ScriptedModel(script=Script([])),
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
    )
    servicer = SwarmServicer(sdk)
    handle = swarm_pb2.PlanHandle(
        steps=[
            swarm_pb2.PlanStepMsg(
                id="S1",
                title="t",
                description="d",
                agent="Tester",
            )
        ]
    )
    result = servicer.RunPlan(handle, None)
    assert result.plan_id
    status = servicer.PlanStatus(swarm_pb2.PlanHandle(plan_id=result.plan_id), None)
    assert status.status == "done"
    assert status.steps_done == 1


def test_grpc_plan_handle_roundtrips_files_and_task() -> None:
    from swarm_sdk.orchestrator.plan import Plan, PlanStep
    from swarm_sdk.serving.grpc import _from_handle, _to_handle

    plan = Plan(
        steps=[
            PlanStep(
                id="S1",
                title="t",
                description="d",
                agent="Coder",
                task="implement_in_files",
                files=["src/a.py", "tests/test_a.py"],
            )
        ]
    )
    restored = _from_handle(_to_handle(plan))
    assert restored.steps[0].task == "implement_in_files"
    assert restored.steps[0].files == ["src/a.py", "tests/test_a.py"]


def test_spawn_plan_returns_handle_and_registers_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from swarm_sdk.orchestrator.plan import Plan, PlanStep
    from swarm_sdk.serving import grpc as grpc_server
    from swarm_sdk.serving.grpc import SwarmServicer

    async def fake_spawn(goal: str, manifests: dict[str, object]) -> Plan:
        del goal, manifests
        return Plan(
            steps=[
                PlanStep(id="S1", title="step", description="do it", agent="Tester")
            ]
        )

    monkeypatch.setattr(grpc_server, "spawn", fake_spawn)
    grpc_server._PLANS.clear()
    grpc_server._RESULTS.clear()

    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        memory_backend="opencl",
    )
    sdk = SwarmSDK(
        settings,
        router_model=ScriptedModel(script=Script([])),
        specialist_model=ScriptedModel(script=Script([])),
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
    )
    servicer = SwarmServicer(sdk)
    handle = servicer.SpawnPlan(
        swarm_pb2.SpawnRequest(goal="test goal"), None
    )
    assert handle.plan_id
    assert len(handle.steps) == 1
    assert handle.steps[0].id == "S1"
    assert handle.plan_id in grpc_server._PLANS


def test_spawn_plan_filters_agents_and_rejects_unknown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from swarm_sdk.orchestrator.plan import Plan, PlanStep
    from swarm_sdk.serving import grpc as grpc_server
    from swarm_sdk.serving.grpc import SwarmServicer

    called_with: dict[str, object] = {}

    async def fake_spawn(goal: str, manifests: dict[str, object]) -> Plan:
        called_with["goal"] = goal
        called_with["manifests"] = set(manifests)
        return Plan(
            steps=[
                PlanStep(id="S1", title="step", description="do it", agent="Tester")
            ]
        )

    monkeypatch.setattr(grpc_server, "spawn", fake_spawn)
    grpc_server._PLANS.clear()
    grpc_server._RESULTS.clear()

    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        memory_backend="opencl",
    )
    sdk = SwarmSDK(
        settings,
        router_model=ScriptedModel(script=Script([])),
        specialist_model=ScriptedModel(script=Script([])),
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
    )
    servicer = SwarmServicer(sdk)

    handle = servicer.SpawnPlan(
        swarm_pb2.SpawnRequest(goal="g", agents=["Tester"]), None
    )
    assert handle.plan_id
    assert called_with["manifests"] == {"Tester"}

    with pytest.raises(ValueError, match="no matching agent manifests"):
        servicer.SpawnPlan(
            swarm_pb2.SpawnRequest(goal="g", agents=["NotAnAgent"]), None
        )


def test_run_plan_reuses_existing_plan_and_reports_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from swarm_sdk.orchestrator.plan import Plan, PlanResult, StepOutput, UsageTotals
    from swarm_sdk.serving import grpc as grpc_server
    from swarm_sdk.serving.grpc import SwarmServicer

    async def fake_run_plan(plan, factory, **_kwargs: object):  # noqa: ANN001, ARG001
        return PlanResult(
            outputs={
                "S1": StepOutput(step_id="S1", agent="Tester", content="ok"),
                "S2": StepOutput(step_id="S2", agent="Tester", content="ok"),
            },
            usage=UsageTotals(),
        )

    monkeypatch.setattr(grpc_server, "run_plan", fake_run_plan)
    grpc_server._PLANS.clear()
    grpc_server._RESULTS.clear()

    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        memory_backend="opencl",
    )
    sdk = SwarmSDK(
        settings,
        router_model=ScriptedModel(script=Script([])),
        specialist_model=ScriptedModel(script=Script([])),
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
    )
    servicer = SwarmServicer(sdk)

    # Seed a plan so RunPlan uses _PLANS rather than request.steps.
    from swarm_sdk.orchestrator.plan import PlanStep

    plan_id = "existing-plan"
    grpc_server._PLANS[plan_id] = Plan(
        steps=[
            PlanStep(id="S1", title="a", description="a", agent="Tester"),
            PlanStep(id="S2", title="b", description="b", agent="Tester"),
        ]
    )

    running = servicer.PlanStatus(
        swarm_pb2.PlanHandle(plan_id=plan_id), None
    )
    assert running.status == "running"
    assert running.steps_total == 2

    result = servicer.RunPlan(
        swarm_pb2.PlanHandle(plan_id=plan_id), None
    )
    assert result.plan_id == plan_id
    assert len(result.outputs) == 2

    done = servicer.PlanStatus(
        swarm_pb2.PlanHandle(plan_id=plan_id), None
    )
    assert done.status == "done"
    assert done.steps_done == 2


def test_plan_status_unknown_plan_is_failed() -> None:
    from swarm_sdk.serving import grpc as grpc_server
    from swarm_sdk.serving.grpc import SwarmServicer

    grpc_server._PLANS.clear()
    grpc_server._RESULTS.clear()

    servicer = SwarmServicer(None)  # type: ignore
    status = servicer.PlanStatus(
        swarm_pb2.PlanHandle(plan_id="missing"), None
    )
    assert status.plan_id == "missing"
    assert status.status == "failed"
    assert status.steps_done == 0
    assert status.steps_total == 0


def test_to_result_msg_records_result_for_status_polling() -> None:
    from swarm_sdk.orchestrator.plan import PlanResult, StepOutput, UsageTotals
    from swarm_sdk.serving import grpc as grpc_server
    from swarm_sdk.serving.grpc import _to_result_msg

    grpc_server._RESULTS.clear()
    result = PlanResult(
        outputs={
            "S1": StepOutput(
                step_id="S1",
                agent="Tester",
                content="done",
                prompt_tokens=10,
                completion_tokens=5,
                cached=True,
                wall_s=0.1,
                status="ok",
            )
        },
        usage=UsageTotals(
            prompt_tokens=10,
            completion_tokens=5,
            llm_calls=1,
            cached_calls=1,
            wall_s=0.1,
        ),
    )
    msg = _to_result_msg("plan-1", result)
    assert msg.plan_id == "plan-1"
    assert len(msg.outputs) == 1
    assert msg.outputs[0].step_id == "S1"
    assert msg.outputs[0].prompt_tokens == 10
    assert msg.outputs[0].cached is True
    assert msg.usage.llm_calls == 1
    assert "plan-1" in grpc_server._RESULTS


def test_serve_creates_started_grpc_server(
    tmp_path: Path,
) -> None:
    import grpc as grpc_lib

    from swarm_sdk.serving.grpc import serve

    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        memory_backend="opencl",
    )
    sdk = SwarmSDK(
        settings,
        router_model=ScriptedModel(script=Script([])),
        specialist_model=ScriptedModel(script=Script([])),
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
    )
    server = serve(sdk, "127.0.0.1", 0)
    assert isinstance(server, grpc_lib.Server)
    server.stop(0)
