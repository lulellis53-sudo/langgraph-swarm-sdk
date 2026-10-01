"""gRPC Run, Recall, and orchestration (SpawnPlan/RunPlan/PlanStatus) service."""

from __future__ import annotations

import asyncio
import concurrent.futures
import uuid

import grpc

from swarm_sdk.agents.manifest import load_all_agent_manifests
from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.execution.executor import install_uvloop
from swarm_sdk.orchestrator import make_factory, run_plan, spawn
from swarm_sdk.orchestrator.plan import Plan, PlanResult
from swarm_sdk.orchestrator.spawn import _validate_plan
from swarm_sdk.pb import swarm_pb2, swarm_pb2_grpc

#: Spawned plans awaiting execution, keyed by plan id (see module docstring).
_PLANS: dict[str, Plan] = {}
#: Completed plan results, keyed by plan id; powers PlanStatus polling.
_RESULTS: dict[str, swarm_pb2.PlanResultMsg] = {}


def _to_handle(plan: Plan) -> swarm_pb2.PlanHandle:
    """Serialize a plan into its wire form, assigning a fresh plan id."""
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
                task=s.task,
                files=s.files,
            )
            for s in plan.steps
        ],
    )


def _from_handle(handle: swarm_pb2.PlanHandle) -> Plan:
    """Rebuild a pydantic plan from its wire form."""
    return Plan(
        steps=[
            {
                "id": s.id,
                "title": s.title,
                "description": s.description,
                "agent": s.agent,
                "task": s.task,
                "files": list(s.files),
                "depends_on": list(s.depends_on),
                "inputs": list(s.inputs),
            }
            for s in handle.steps
        ]
    )


def _to_result_msg(plan_id: str, result: PlanResult) -> swarm_pb2.PlanResultMsg:
    """Serialize a plan result to wire form and record it for status polling."""
    _RESULTS[plan_id] = swarm_pb2.PlanResultMsg(
        plan_id=plan_id,
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
    """Implements ``swarm.v1.SwarmService``: single-run, memory recall, and the
    three orchestration RPCs (spawn a plan, execute it, poll its status)."""

    def __init__(self, sdk: SwarmSDK) -> None:
        self.sdk = sdk

    def Run(
        self,
        request: swarm_pb2.RunRequest,
        context: grpc.ServicerContext | None,
    ) -> swarm_pb2.RunResponse:
        """Single text run through the handoff swarm (existing behavior)."""
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
        """Hybrid memory recall over the store backing the SDK."""
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
        """Decompose a goal into a plan via the Orchestrator agent."""
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
        """Execute a plan through the LangGraph orchestration engine."""
        plan_id = request.plan_id or uuid.uuid4().hex
        plan = _PLANS.get(plan_id)
        if plan is None:
            plan = _from_handle(request)
        manifests = load_all_agent_manifests()
        try:
            _validate_plan(plan, manifests)
        except ValueError as exc:
            if context is not None:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            raise
        _PLANS[plan_id] = plan
        result = asyncio.run(
            run_plan(
                plan,
                make_factory(manifests),
                max_concurrency=self.sdk.file_config.parallelism.max_concurrency,
            )
        )
        return _to_result_msg(plan_id, result)

    def PlanStatus(
        self,
        request: swarm_pb2.PlanHandle,
        context: grpc.ServicerContext | None,
    ) -> swarm_pb2.PlanStatusMsg:
        """Poll the status of a plan."""
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
    """Start an insecure gRPC server with the swarm service registered."""
    server = grpc.server(concurrent.futures.ThreadPoolExecutor(max_workers=8))
    swarm_pb2_grpc.add_SwarmServiceServicer_to_server(SwarmServicer(sdk), server)
    bound_port = server.add_insecure_port(f"{host}:{port}")
    if bound_port == 0:
        raise RuntimeError(f"could not bind gRPC server to {host}:{port}")
    server.start()
    return server


def main() -> None:
    """Entrypoint for the ``swarm-grpc`` script: uvloop + serve forever."""
    install_uvloop()
    settings = Settings()
    server = serve(SwarmSDK.from_settings(), settings.api_host, settings.grpc_port)
    server.wait_for_termination()


__all__ = ["SwarmServicer", "main", "serve"]
