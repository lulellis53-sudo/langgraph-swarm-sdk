"""gRPC Run, Recall, and orchestration (SpawnPlan/RunPlan/PlanStatus) service."""

from __future__ import annotations

import asyncio
import concurrent.futures
import uuid

import grpc

from swarm_sdk.agents.manifest import load_all_agent_manifests
from swarm_sdk.config import Settings
from swarm_sdk.orchestrator import make_factory, run_plan, spawn
from swarm_sdk.orchestrator.plan import Plan, PlanResult
from swarm_sdk.pb import swarm_pb2, swarm_pb2_grpc
from swarm_sdk.runtime import install_uvloop
from swarm_sdk.swarm import SwarmSDK

_PLANS: dict[str, Plan] = {}
_RESULTS: dict[str, swarm_pb2.PlanResultMsg] = {}


def _to_handle(plan: Plan) -> swarm_pb2.PlanHandle:
    return swarm_pb2.PlanHandle(
        plan_id=uuid.uuid4().hex,
        steps=[
            swarm_pb2.PlanStepMsg(
                id=s.id,
                title=s.title,
                description=s.description,
                agent=s.agent,
                depends_on=s.depends_on,
                inputs=s.inputs,
            )
            for s in plan.steps
        ],
    )


def _from_handle(handle: swarm_pb2.PlanHandle) -> Plan:
    return Plan(
        steps=[
            {
                "id": s.id,
                "title": s.title,
                "description": s.description,
                "agent": s.agent,
                "depends_on": list(s.depends_on),
                "inputs": list(s.inputs),
            }
            for s in handle.steps
        ]
    )


def _to_result_msg(plan_id: str, result: PlanResult) -> swarm_pb2.PlanResultMsg:
    _RESULTS[plan_id] = swarm_pb2.PlanResultMsg(
        outputs=[
            swarm_pb2.StepOutputMsg(
                step_id=o.step_id,
                agent=o.agent,
                content=o.content,
                prompt_tokens=o.prompt_tokens,
                completion_tokens=o.completion_tokens,
                cached=o.cached,
                wall_s=o.wall_s,
                status=o.status,
            )
            for o in result.outputs.values()
        ],
        usage=swarm_pb2.UsageMsg(
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            llm_calls=result.usage.llm_calls,
            cached_calls=result.usage.cached_calls,
            wall_s=result.usage.wall_s,
        ),
    )
    return _RESULTS[plan_id]


class SwarmServicer(swarm_pb2_grpc.SwarmServiceServicer):
    def __init__(self, sdk: SwarmSDK) -> None:
        self.sdk = sdk

    def Run(
        self,
        request: swarm_pb2.RunRequest,
        context: grpc.ServicerContext | None,
    ) -> swarm_pb2.RunResponse:
        del context
        result = asyncio.run(self.sdk.run(request.text, request.thread_id or "default"))
        return swarm_pb2.RunResponse(
            text=result.text,
            cached=result.cached,
            active_agent=result.active_agent,
            tokens=result.tokens,
            mode=result.mode,
        )

    def Recall(
        self,
        request: swarm_pb2.RecallRequest,
        context: grpc.ServicerContext | None,
    ) -> swarm_pb2.RecallResponse:
        del context
        hits = self.sdk.recall(request.query, request.top_k or 4)
        return swarm_pb2.RecallResponse(
            hits=[
                swarm_pb2.MemoryHit(id=hit.id, text=hit.text, score=hit.score) for hit in hits
            ]
        )

    def SpawnPlan(
        self,
        request: swarm_pb2.SpawnRequest,
        context: grpc.ServicerContext | None,
    ) -> swarm_pb2.PlanHandle:
        manifests = load_all_agent_manifests()
        if request.agents:
            wanted = set(request.agents)
            manifests = {k: v for k, v in manifests.items() if k in wanted}
        if not manifests:
            if context is None:
                raise ValueError("no matching agent manifests")
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "no matching agent manifests")
        plan = asyncio.run(spawn(request.goal, manifests))
        handle = _to_handle(plan)
        _PLANS[handle.plan_id] = plan
        return handle

    def RunPlan(
        self,
        request: swarm_pb2.PlanHandle,
        context: grpc.ServicerContext | None,
    ) -> swarm_pb2.PlanResultMsg:
        del context
        plan = _PLANS.get(request.plan_id) or _from_handle(request)
        manifests = load_all_agent_manifests()
        result = asyncio.run(run_plan(plan, make_factory(manifests)))
        return _to_result_msg(request.plan_id or uuid.uuid4().hex, result)

    def PlanStatus(
        self,
        request: swarm_pb2.PlanHandle,
        context: grpc.ServicerContext | None,
    ) -> swarm_pb2.PlanStatusMsg:
        del context
        plan_id = request.plan_id
        result = _RESULTS.get(plan_id)
        plan = _PLANS.get(plan_id)
        steps_total = len(request.steps) or (len(plan.steps) if plan else 0)
        if result is not None:
            return swarm_pb2.PlanStatusMsg(
                plan_id=plan_id,
                status="done",
                steps_done=len(result.outputs),
                steps_total=steps_total,
            )
        known = len(request.steps) or steps_total
        return swarm_pb2.PlanStatusMsg(
            plan_id=plan_id,
            status="running" if known else "failed",
            steps_done=0,
            steps_total=steps_total,
        )


def serve(sdk: SwarmSDK, host: str = "127.0.0.1", port: int = 50051) -> grpc.Server:
    server = grpc.server(concurrent.futures.ThreadPoolExecutor(max_workers=8))
    swarm_pb2_grpc.add_SwarmServiceServicer_to_server(SwarmServicer(sdk), server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    return server


def main() -> None:
    install_uvloop()
    settings = Settings()
    server = serve(SwarmSDK.from_settings(), settings.api_host, settings.grpc_port)
    server.wait_for_termination()
