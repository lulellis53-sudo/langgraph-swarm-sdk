"""Fan out independent tasks so each specialist sees only its own brief."""

import asyncio

from pydantic import BaseModel, Field

from swarm_sdk.providers import complete
from swarm_sdk.tokens import count_text

TASK_SYSTEM = "Answer only the task. Be brief."
SYNTH_SYSTEM = "Merge the JSON briefs into one short answer."


class HandoffPayload(BaseModel):
    summary: str = Field(max_length=280)
    ask: str = Field(max_length=200)
    facts: list[str] = Field(default_factory=list, max_length=5)


class SpecialistResult(BaseModel):
    agent: str
    payload: HandoffPayload
    tokens: int


async def fan_out(model: object, tasks: list[str], agent: str = "specialist") -> tuple[str, int]:
    from langchain_core.language_models.chat_models import BaseChatModel

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

    results = await asyncio.gather(*(one(task) for task in tasks))
    brief = "\n".join(item.payload.model_dump_json() for item in results)
    merged = await complete(model, SYNTH_SYSTEM, brief)
    tokens = sum(item.tokens for item in results) + count_text(brief) + count_text(merged)
    return merged, tokens
