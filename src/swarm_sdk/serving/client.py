"""LangGraph Server client (``langgraph_sdk``) for remote swarm runs.

When ``Settings.server_url`` points at a LangGraph Server deployment of this
SDK (``langgraph.json`` at the repo root), ``SwarmSDK.run`` delegates to
:func:`run_on_server` instead of running the graph in-process. Threads live
server-side with durable checkpoints.
"""

from __future__ import annotations

from typing import Any

DEFAULT_GRAPH_ID = "swarm"


async def run_on_server(
    text: str,
    thread_id: str = "default",
    *,
    server_url: str,
    graph_id: str = DEFAULT_GRAPH_ID,
) -> dict[str, Any]:
    """Run ``text`` on a LangGraph Server deployment of the swarm graph.

    Args:
        text: The user message for the swarm.
        thread_id: Server-side thread id (durable per-thread checkpoints).
        server_url: Base URL of the LangGraph Server, e.g. ``http://127.0.0.1:2024``.
        graph_id: Graph id from ``langgraph.json`` (default ``"swarm"``).

    Returns:
        A ``RunResult``-shaped payload: ``text`` (last AI message),
        ``active_agent``, ``tokens`` (provider-reported total when available),
        ``cached=False``, ``mode="server"``.
    """
    from langgraph_sdk import get_client

    from swarm_sdk.models.chat import last_ai_text, usage_tokens

    client = get_client(url=server_url)
    state: Any = await client.runs.wait(
        thread_id,
        graph_id,
        input={"messages": [{"role": "user", "content": text}]},
        if_not_exists="create",
    )
    if not isinstance(state, dict):
        raise TypeError(f"server returned {type(state).__name__}, expected a state dict")
    messages = state.get("messages", [])
    if not isinstance(messages, list):
        messages = []
    reported = usage_tokens(messages)
    return {
        "text": last_ai_text(messages),
        "cached": False,
        "active_agent": str(state.get("active_agent") or graph_id),
        "tokens": reported if reported is not None else 0,
        "mode": "server",
    }


__all__ = ["DEFAULT_GRAPH_ID", "run_on_server"]
