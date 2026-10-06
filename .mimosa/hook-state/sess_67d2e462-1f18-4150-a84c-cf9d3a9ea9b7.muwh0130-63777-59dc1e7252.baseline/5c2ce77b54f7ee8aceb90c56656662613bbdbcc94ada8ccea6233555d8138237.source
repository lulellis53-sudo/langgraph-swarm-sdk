"""Per-step Jev gate: a safety verdict and a tier hint before a plan step runs.

The gate uses the **local** deterministic router only. Step descriptions can contain
repository content, so they never go to a hosted Jev endpoint from here. A step the Noul
check rejects does not run, and neither do steps that depend on it.
"""

from __future__ import annotations

import logging

from swarm_sdk.config.settings import Settings
from swarm_sdk.core.jev_router import JevRouter
from swarm_sdk.orchestrator.plan import JevDecision, PlanStep, StepOutput

logger = logging.getLogger(__name__)


def jev_for(settings: Settings) -> JevRouter | None:
    """Return the router for per-step routing, or ``None`` when it is switched off.

    Args:
        settings: Runtime settings; ``jev_plan_routing`` turns the gate on.

    Returns:
        A local router with no endpoint, or ``None`` when the setting is off.
    """
    if not settings.jev_plan_routing:
        return None
    router = JevRouter(endpoint=None, api_key="")
    # JEV_ENDPOINT in the environment must not send step text off the machine.
    router.endpoint = None
    return router


def assess_step(step: PlanStep, router: JevRouter) -> JevDecision:
    """Run the Noul safety check and the Score tier for one step.

    Args:
        step: The step about to run. Only its title, description and files are shown
            to the router.
        router: The router to ask.

    Returns:
        The combined decision.
    """
    task = f"{step.title}\n{step.description}"
    context = "\n".join(step.files)
    noul = router.evaluate_noul(task, context)
    score = router.evaluate_score(task, context)
    return JevDecision(
        safe=noul.decision,
        reason=noul.reasoning_tag,
        score=score.score,
        tier=score.model_tier,
        latency_ms=noul.latency_ms + score.latency_ms,
    )


def try_assess_step(step: PlanStep, router: JevRouter) -> JevDecision | None:
    """Like :func:`assess_step`, but a router failure returns ``None``.

    Jev must never make a plan fail that would otherwise succeed, so the caller runs the
    step as if Jev were off. The failure is logged without the step text.
    """
    try:
        return assess_step(step, router)
    except Exception as exc:
        logger.debug("Jev assessment of step %s failed (%s); running it unrouted", step.id, exc)
        return None


def blocked_output(step: PlanStep, decision: JevDecision) -> StepOutput:
    """Build the output for a step that must not run.

    Args:
        step: The blocked step.
        decision: The verdict that blocked it.

    Returns:
        A ``blocked`` output with no content and no token cost.
    """
    return StepOutput(
        step_id=step.id,
        agent=step.agent,
        content="",
        status="blocked",
        handoff_errors=[f"jev: {decision.reason}"],
        jev_decision=decision,
    )


def is_jev_blocked(output: StepOutput | None) -> bool:
    """True when ``output`` is a step Jev refused to run."""
    return output is not None and output.jev_decision is not None and not output.jev_decision.safe


def dependency_block(step: PlanStep, outputs: dict[str, StepOutput]) -> JevDecision | None:
    """Return a blocking decision when a step depends on a Jev-blocked step.

    Args:
        step: The step about to run.
        outputs: Outputs of the steps that already finished.

    Returns:
        A decision naming the first blocked dependency, or ``None``.
    """
    for dep in step.depends_on:
        if is_jev_blocked(outputs.get(dep)):
            return JevDecision(
                safe=False,
                reason=f"dependency {dep} blocked",
                score=0.0,
                tier="",
                latency_ms=0.0,
            )
    return None


__all__ = [
    "assess_step",
    "blocked_output",
    "dependency_block",
    "is_jev_blocked",
    "jev_for",
    "try_assess_step",
]
