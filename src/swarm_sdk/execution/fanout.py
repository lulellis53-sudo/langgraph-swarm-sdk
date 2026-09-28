"""Fan out independent tasks so each specialist sees only its own brief."""

from __future__ import annotations

from pydantic import BaseModel, Field

from swarm_sdk.prompting.budget import count_text

TASK_SYSTEM = "Answer only the task. Be brief."
SYNTH_SYSTEM = "Merge the JSON briefs into one short answer."


class HandoffPayload(BaseModel):
    """Compact specialist result passed into the synthesizer.

    Attributes:
        summary: Short answer summary (max 280 chars).
        ask: Original task text (max 200 chars).
        facts: Up to five short fact strings.
    """

    summary: str = Field(max_length=280)
    ask: str = Field(max_length=200)
    facts: list[str] = Field(default_factory=list, max_length=5)


class SpecialistResult(BaseModel):
    """One specialist's handoff plus token usage.

    Attributes:
        agent: Agent label for usage rollups.
        payload: Structured handoff body.
        tokens: Tokens counted for this specialist answer.
    """

    agent: str
    payload: HandoffPayload
    tokens: int


async def fan_out(
    model: object,
    tasks: list[str],
    agent: str = "specialist",
    *,
    max_concurrency: int = 8,
) -> tuple[str, int]:
    """Run independent tasks in parallel and synthesize one brief answer.

    Args:
        model: LangChain ``BaseChatModel`` instance.
        tasks: Independent task strings (each sees only its own brief).
        agent: Agent name stamped on each ``SpecialistResult``.
        max_concurrency: Cap on concurrent specialist calls.

    Returns:
        Tuple of ``(merged_answer, total_tokens)``.

    Raises:
        TypeError: If ``model`` is not a ``BaseChatModel``.
    """
    from langchain_core.language_models.chat_models import BaseChatModel

    from swarm_sdk.models.chat import complete
    from swarm_sdk.models.selection import bounded_gather

    if not isinstance(model, BaseChatModel):
        raise TypeError("fan_out requires a chat model")

    async def one(task: str) -> SpecialistResult:
        answer = await complete(model, TASK_SYSTEM, task)
        payload = HandoffPayload(
            summary=answer[:280],
            ask=task[:200],
            facts=[answer[:120]] if answer else [],
        )
        return SpecialistResult(agent=agent, payload=payload, tokens=count_text(answer))

    factories = [lambda t=task: one(t) for task in tasks]
    results = await bounded_gather(factories, max_concurrency=max_concurrency)
    brief = "\n".join(item.payload.model_dump_json() for item in results)
    merged = await complete(model, SYNTH_SYSTEM, brief)
    tokens = sum(item.tokens for item in results) + count_text(brief) + count_text(merged)
    return merged, tokens


__all__ = [
    "HandoffPayload",
    "SpecialistResult",
    "SYNTH_SYSTEM",
    "TASK_SYSTEM",
    "fan_out",
]
