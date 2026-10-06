"""Execution domain: event-loop offloading and parallel fan-out.

GIL / free-threading concurrency caps for pools and orchestrator waves.
A shared thread pool runs blocking provider SDK calls off the event loop.
Fan-out runs independent tasks in parallel and synthesizes one brief answer.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import sys
from collections.abc import Callable

from pydantic import BaseModel, Field

TASK_SYSTEM = "Answer only the task. Be brief."
SYNTH_SYSTEM = "Merge the JSON briefs into one short answer."


# GIL/free-threading policy lives in the single audited module `concurrency.py`
# (test_gil_probe_only_in_concurrency_module); re-exported here for convenience.
from swarm_sdk.execution.concurrency import (  # noqa: E402
    FREE_THREADED_POOL_WORKERS,
    GIL_POOL_WORKERS,
    gil_enabled,
    parallel_cap,
)


def _pool_workers() -> int:
    """Worker count for the shared thread pool, matched to the interpreter build."""
    return parallel_cap()


_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=_pool_workers(), thread_name_prefix="swarm"
)


def install_uvloop() -> None:
    """Install uvloop as the asyncio policy on platforms that support it.

    No-op on Windows. Call once at process entrypoint (e.g. ``swarm-grpc``)
    before any event loop is created.
    """
    if sys.platform == "win32":
        return
    import uvloop

    uvloop.install()


async def offload[T](fn: Callable[..., T], *args: object) -> T:
    """Run a blocking function on the shared thread pool.

    Args:
        fn: Synchronous callable (typically a provider SDK call).
        args: Positional arguments for ``fn``.

    Returns:
        The function's result, awaited without blocking the event loop.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_POOL, fn, *args)


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

    from swarm_sdk.models.chat import complete_with_usage
    from swarm_sdk.models.selection import bounded_gather

    if not isinstance(model, BaseChatModel):
        raise TypeError("fan_out requires a chat model")

    async def one(task: str) -> SpecialistResult:
        answer, answer_tokens = await complete_with_usage(model, TASK_SYSTEM, task)
        payload = HandoffPayload(
            summary=answer[:280],
            ask=task[:200],
            # Only the overflow beyond the summary goes into facts: repeating
            # the summary head would just buy the synthesizer duplicate tokens.
            facts=[answer[280:400]] if len(answer) > 280 else [],
        )
        return SpecialistResult(agent=agent, payload=payload, tokens=answer_tokens)

    factories = [lambda t=task: one(t) for task in tasks]
    results = await bounded_gather(factories, max_concurrency=max_concurrency)
    brief = "\n".join(item.payload.model_dump_json() for item in results)
    merged, merged_tokens = await complete_with_usage(model, SYNTH_SYSTEM, brief)
    tokens = sum(item.tokens for item in results) + merged_tokens
    return merged, tokens


__all__ = [
    "FREE_THREADED_POOL_WORKERS",
    "GIL_POOL_WORKERS",
    "HandoffPayload",
    "SpecialistResult",
    "SYNTH_SYSTEM",
    "TASK_SYSTEM",
    "fan_out",
    "gil_enabled",
    "install_uvloop",
    "offload",
    "parallel_cap",
]
