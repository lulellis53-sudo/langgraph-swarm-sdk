"""gRPC Run, Recall, and orchestration (SpawnPlan/RunPlan/PlanStatus) service.

Synchronous gRPC servicer methods drive the async engine with
:func:`asyncio.run` per call (grpc handlers run on their own threads, so each
call gets a fresh loop — no shared-loop hazards).

Plan/result keep-alive is in-process and best-effort: ``_PLANS`` and
``_RESULTS`` are module-level dicts keyed by plan id. That is enough for a
single-node server and short-lived clients (SpawnPlan → RunPlan → PlanStatus);
a multi-node deployment would swap these for a shared store.
"""

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

#: Spawned plans awaiting execution, keyed by plan id (see module docstring).
_PLANS: dict[str, Plan] = {}
#: Completed plan results, keyed by plan id; powers PlanStatus polling.
_RESULTS: dict[str, swarm_pb2.PlanResultMsg] = {}


def _to_handle(plan: Plan) -> swarm_pb2.PlanHandle:
    """Serialize a plan into its wire form, assigning a fresh plan id.

    Args:
        plan: The validated plan returned by :func:`spawn`.

    Returns:
        A ``PlanHandle`` whose ``plan_id`` the client echoes back to
        ``RunPlan``/``PlanStatus``.
    """
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
    """Rebuild a pydantic plan from its wire form.

    Lets clients submit a hand-built plan to ``RunPlan`` without a prior
    ``SpawnPlan`` call; pydantic coerces the plain dicts into ``PlanStep``.

    Args:
        handle: Wire form with at least ``steps`` populated.

    Returns:
        The validated plan (raises pydantic.ValidationError on bad input).
    """
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
    """Serialize a plan result to wire form and record it for status polling.

    Args:
        plan_id: Id under which to remember the result.
        result: The engine's plan result.

    Returns:
        The ``PlanResultMsg`` (also stored in ``_RESULTS``).
    """
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
        """Decompose a goal into a plan via the Orchestrator agent.

        Args:
            request: The goal plus an optional agent-name filter.

        Returns:
            A plan handle (id + steps) to pass to ``RunPlan``.

        Aborts:
            INVALID_ARGUMENT: When the agent filter matches no manifests.
        """
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
        """Execute a plan through the LangGraph orchestration engine.

        Accepts either a handle returned by ``SpawnPlan`` (looked up in
        ``_PLANS``) or a client-built handle (parsed via :func:`_from_handle`),
        so callers can run hand-authored plans without an orchestrator call.

        Returns:
            Per-step outputs plus aggregated usage totals; the result is also
            recorded for subsequent ``PlanStatus`` polls.
        """
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
        """Poll the status of a plan: done (result recorded), running (known
        but not yet executed), or failed (unknown id and no steps)."""
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
    """Start an insecure gRPC server with the swarm service registered.

    Args:
        sdk: Configured ``SwarmSDK`` instance for Run/Recall.
        host: Bind address.
        port: Bind port.

    Returns:
        The started ``grpc.Server`` (callers may ``wait_for_termination``).
    """
    server = grpc.server(concurrent.futures.ThreadPoolExecutor(max_workers=8))
    swarm_pb2_grpc.add_SwarmServiceServicer_to_server(SwarmServicer(sdk), server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    return server


def main() -> None:
    """Entrypoint for the ``swarm-grpc`` script: uvloop + serve forever."""
    install_uvloop()
    settings = Settings()
    server = serve(SwarmSDK.from_settings(), settings.api_host, settings.grpc_port)
    server.wait_for_termination()
