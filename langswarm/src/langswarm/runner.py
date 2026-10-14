"""High-level execution entry points: run and stream a swarm conversation."""

from typing import Any


def _config(thread_id: str, config: dict[str, Any] | None) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}, **(config or {})}


def run_swarm(app, message: str, *, thread_id: str, config: dict[str, Any] | None = None) -> str:
    """Run one conversational turn through the swarm and return the final text."""
    inputs = {"messages": [{"role": "user", "content": message}]}
    result = app.invoke(inputs, _config(thread_id, config))
    return result["messages"][-1].content


async def stream_swarm(app, message: str, *, thread_id: str, config: dict[str, Any] | None = None):
    """Stream text deltas from the swarm as they are produced."""
    inputs = {"messages": [{"role": "user", "content": message}]}
    async for chunk, _metadata in app.astream(
        inputs, _config(thread_id, config), stream_mode="messages"
    ):
        content = getattr(chunk, "content", None)
        if isinstance(content, str) and content:
            yield content
