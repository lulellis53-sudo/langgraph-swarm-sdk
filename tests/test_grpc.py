from pathlib import Path

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
    from swarm_sdk import grpc_server
    from swarm_sdk.serving.grpc import SwarmServicer
    from swarm_sdk.orchestrator.plan import PlanResult, StepOutput, UsageTotals

    async def fake_run_plan(plan, factory):  # noqa: ANN001, ARG001
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
