"""Long-term memory through the Mem0 platform API (``mem0`` extra).

The platform client talks to the hosted API at api.mem0.ai and authenticates
with ``MEM0_API_KEY``. The import is deferred to first use; the tool functions
surface a clear error when the key or the extra is missing, which the model
can report back instead of crashing the swarm.
"""


def _client():
    import os

    try:
        from mem0 import MemoryClient
    except ImportError as error:
        raise RuntimeError(
            "The 'mem0' extra is required for long-term memory (uv sync --extra mem0)."
        ) from error

    api_key = os.environ.get("MEM0_API_KEY")
    if not api_key:
        raise RuntimeError("MEM0_API_KEY is not set; get a key at https://app.mem0.ai.")
    return MemoryClient(api_key=api_key)


def mem0_remember_tool():
    """Return the long-term memory write tool used by the MemoryKeeper."""

    def remember(content: str, user_id: str = "default") -> str:
        """Store a durable fact or preference in long-term memory."""
        result = _client().add(content, user_id=user_id)
        stored = result.get("results", []) if isinstance(result, dict) else result
        return f"Stored {len(stored)} memory record(s) in long-term memory."

    return remember


def mem0_recall_tool():
    """Return the long-term memory read tool used by the Historian."""

    def recall(query: str, user_id: str = "default") -> str:
        """Search long-term memory for facts relevant to the query."""
        hits = _client().search(query, filters={"user_id": user_id})
        if not hits:
            return "Nothing relevant was found in long-term memory."
        return "\n".join(f"- {hit.get('memory', hit)}" for hit in hits)

    return recall
