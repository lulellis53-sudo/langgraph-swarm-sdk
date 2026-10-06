"""PydanticAI specialist nodes for the LangGraph swarm.

``pydantic_ai_node`` builds a compiled single-node graph that ``langgraph_swarm.create_swarm``
accepts like any ``create_agent`` result. The node's PydanticAI agent returns either plain text
(the answer) or a typed ``Handoff`` naming a peer; a handoff becomes a parent-graph ``Command``
with the same state update ``create_handoff_tool`` produces (``active_agent`` + a notice).

Requires the ``pydantic-ai`` extra (``uv sync --extra pydantic-ai``); the import is lazy.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, Field, create_model

if TYPE_CHECKING:
    from langchain_core.messages import AnyMessage
    from langgraph.graph.state import CompiledStateGraph
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import Model

CONTINUE_PROMPT = "Continue helping the user."


class Handoff(BaseModel):
    """Base schema for a swarm handoff; ``handoff_type`` narrows ``agent`` to real peers."""

    agent: str = Field(description="Name of the peer agent that should take over.")
    reason: str = Field(default="", description="One sentence on why the peer fits better.")


def handoff_type(peers: Sequence[str]) -> type[Handoff]:
    """Return a ``Handoff`` subclass whose ``agent`` is a ``Literal`` of ``peers``.

    Raises:
        ValueError: If ``peers`` is empty.
    """
    if not peers:
        raise ValueError("handoff_type needs at least one peer")
    literal = cast("type", Literal.__getitem__(tuple(peers)))
    return create_model(
        "Handoff",
        __base__=Handoff,
        agent=(literal, Field(description=Handoff.model_fields["agent"].description)),
    )


def build_agent(
    name: str,
    model: Model | str,
    instructions: str,
    peers: Sequence[str],
) -> Agent[None, Any]:
    """Create the PydanticAI agent: text answer or typed handoff to one of ``peers``."""
    from pydantic_ai import Agent

    outputs: list[type] = [str]
    if peers:
        outputs.append(handoff_type(peers))
    return Agent(model, name=name, instructions=instructions, output_type=outputs)


def to_model_history(messages: Sequence[AnyMessage]) -> tuple[list[ModelMessage], str]:
    """Convert swarm messages to PydanticAI history plus the prompt for this turn.

    Only text from human and AI messages is kept (tool calls and handoff tool messages are
    dropped). A trailing human message becomes the prompt; otherwise ``CONTINUE_PROMPT``.
    """
    from langchain_core.messages import AIMessage, HumanMessage
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart

    history: list[ModelMessage] = []
    prompt = CONTINUE_PROMPT
    last_index = len(messages) - 1
    for index, message in enumerate(messages):
        text = message.text if isinstance(message, (HumanMessage, AIMessage)) else ""
        if not text:
            continue
        if isinstance(message, HumanMessage):
            if index == last_index:
                prompt = text
            else:
                history.append(ModelRequest.user_text_prompt(text))
        else:
            history.append(ModelResponse(parts=[TextPart(content=text)]))
    return history, prompt


def pydantic_ai_node(
    name: str,
    model: Model | str,
    instructions: str,
    peers: Sequence[str],
) -> CompiledStateGraph:
    """Compile a swarm-compatible node backed by a PydanticAI agent.

    Args:
        name: Node name; must equal the agent name used in ``create_swarm``.
        model: A PydanticAI model instance or ``"provider:model"`` string.
        instructions: The node's system prompt.
        peers: Names of the other swarm nodes this node may hand off to.

    Returns:
        A compiled graph named ``name``, ready for ``create_swarm([...])``.
    """
    from langchain_core.messages import AIMessage
    from langgraph.graph import START, StateGraph
    from langgraph.types import Command
    from langgraph_swarm import SwarmState

    agent = build_agent(name, model, instructions, peers)

    async def _run(state: SwarmState) -> dict[str, Any] | Command:
        history, prompt = to_model_history(state["messages"])
        result = await agent.run(prompt, message_history=history)
        output = result.output
        if isinstance(output, Handoff):
            notice = f"Transferred to {output.agent}" + (
                f": {output.reason}" if output.reason else ""
            )
            return Command(
                goto=output.agent,
                graph=Command.PARENT,
                update={
                    "messages": [AIMessage(content=notice, name=name)],
                    "active_agent": output.agent,
                },
            )
        return {"messages": [AIMessage(content=str(output), name=name)]}

    # langgraph_swarm's own SwarmState (a MessagesState TypedDict) is not seen as StateLike.
    builder = StateGraph(SwarmState)  # ty: ignore[invalid-argument-type]
    builder.add_node("agent", _run)
    builder.add_edge(START, "agent")
    return builder.compile(name=name)


__all__ = ["Handoff", "build_agent", "handoff_type", "pydantic_ai_node", "to_model_history"]
