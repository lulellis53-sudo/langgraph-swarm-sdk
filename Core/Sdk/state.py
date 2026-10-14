"""LangGraph Swarm State Schema.

Defines the state structure passed through LangGraph swarm nodes and handoff tools.
Follows official LangGraph and LangGraph-Swarm conventions.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class SwarmState(TypedDict, total=False):
    """Canonical multi-agent swarm state container.

    Attributes:
        messages: Sequence of chat messages accumulated across agent handoffs,
            reduced using `add_messages`.
        active_agent: The name of the agent currently holding the conversational floor.
        context: Optional dictionary containing arbitrary user or execution metadata.
        handoff_history: Log of agent handoff transitions for observability.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    active_agent: str
    context: dict[str, Any]
    handoff_history: Annotated[list[dict[str, str]], operator.add]


__all__ = ["SwarmState"]
