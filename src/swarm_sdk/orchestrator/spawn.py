"""Main-agent entry: the Orchestrator decomposes a goal into a validated Plan."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from pydantic import ValidationError

from swarm_sdk.agents.manifest import AgentManifest, agents_root
from swarm_sdk.providers import complete, load_chat_model

from .graph import WorkerFactory
from .plan import Plan, PlanStep
from .worker import WorkerAgent

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from swarm_sdk.cache import SemanticCache

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

PLAN_PROMPT = """Decompose the goal into a JSON plan for the available agents.

Goal: {goal}

Available agents (name — role):
{agents}

Rules: small parallel steps; declare only real dependencies in depends_on; inputs lists
the step ids whose outputs this step needs; use only the agent names above.
The JSON shape:
{{"steps": [{{"id": "S1", "title": "...", "description": "...", "agent": "<AgentName>",
"depends_on": [], "inputs": []}}]}}"""


def _model_name(manifest: AgentManifest) -> str:
    if not manifest.model:
        raise RuntimeError(f"agent {manifest.name} has no model in its manifest")
    return manifest.model


def _fallback_plan(goal: str, manifests: dict[str, AgentManifest]) -> Plan:
    name = next(iter(manifests), "Orchestrator")
    return Plan(
        steps=[
            PlanStep(
                id="S1",
                title="handle goal directly",
                description=goal,
                agent=name,
            )
        ]
    )


async def spawn(
    goal: str,
    manifests: dict[str, AgentManifest],
    *,
    model_override: BaseChatModel | None = None,
) -> Plan:
    """Ask the Orchestrator agent for a JSON plan; validate into Plan.

    Retries once on validation failure, then falls back to a single-step plan
    so a malformed orchestrator answer never blocks the swarm.
    """
    orchestrator = manifests.get("Orchestrator") or next(iter(manifests.values()))
    roster = "\n".join(f"- {m.name}: {m.role}" for m in manifests.values())
    prompt = PLAN_PROMPT.format(goal=goal, agents=roster)

    if model_override is not None:
        model = model_override
    else:
        model = load_chat_model(_model_name(orchestrator))
    last_error: Exception | None = None
    for _ in range(2):
        raw = await complete(model, orchestrator.role, prompt)
        match = _JSON_OBJECT.search(raw)
        if match is None:
            last_error = ValueError(f"orchestrator returned no JSON: {raw[:120]!r}")
            continue
        try:
            plan = Plan.model_validate(json.loads(match.group(0)))
        except (ValidationError, json.JSONDecodeError) as exc:
            last_error = exc
            continue
        try:
            _validate_agents(plan, manifests)
        except ValueError as exc:
            last_error = exc
            continue
        return plan
    del last_error  # the fallback plan stands on its own
    return _fallback_plan(goal, manifests)


def _validate_agents(plan: Plan, manifests: dict[str, AgentManifest]) -> None:
    unknown = [s.agent for s in plan.steps if s.agent not in manifests]
    if unknown:
        raise ValueError(f"plan references unknown agents: {unknown}")
    known: set[str] = set()
    for step in plan.steps:
        missing = [d for d in step.depends_on if d not in known]
        if missing:
            raise ValueError(f"step {step.id} depends on unknown or later step {missing}")
        known.add(step.id)


def make_factory(
    manifests: dict[str, AgentManifest],
    *,
    cache: SemanticCache | None = None,
    model_override: BaseChatModel | None = None,
) -> WorkerFactory:
    root = str(agents_root())

    def factory(step: PlanStep) -> WorkerAgent:
        return WorkerAgent(
            manifests[step.agent],
            agents_root=root,
            cache=cache,
            model_override=model_override,
        )

    return factory
