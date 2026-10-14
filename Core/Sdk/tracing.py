"""LangSmith Observability and Tracing.

Provides telemetry, project management, and run callback handlers
for LangGraph swarm executions using official LangSmith APIs.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)


def is_langsmith_enabled() -> bool:
    """Return True if LangSmith tracing is actively configured in the environment."""
    return (
        os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true"
        and bool(os.getenv("LANGCHAIN_API_KEY"))
    )


def get_langsmith_client() -> Any | None:
    """Retrieve the active LangSmith Client instance.

    Returns None if LangSmith is not installed or unconfigured.
    """
    if not is_langsmith_enabled():
        return None

    try:
        from langsmith import Client

        return Client(
            api_key=os.getenv("LANGCHAIN_API_KEY"),
            api_url=os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"),
        )
    except ImportError:
        logger.debug("langsmith package is not installed; tracing disabled.")
        return None
    except Exception as exc:
        logger.warning("Failed to initialize LangSmith client: %s", exc)
        return None


class SwarmTracerCallbackHandler(BaseCallbackHandler):
    """Callback handler capturing multi-agent swarm handoffs, latency, and tokens."""

    def __init__(self, project_name: str | None = None) -> None:
        super().__init__()
        self.project_name = project_name or os.getenv("LANGCHAIN_PROJECT", "swarm-sdk")
        self.active_agent: str = "unknown"
        self.handoff_count: int = 0
        self.total_tokens: int = 0

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Accumulate token counts across agent turns."""
        llm_output = response.llm_output or {}
        token_usage = llm_output.get("token_usage", {})
        if token_usage:
            self.total_tokens += token_usage.get("total_tokens", 0)

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, **kwargs: Any) -> None:
        """Detect agent handoff tool triggers."""
        tool_name = serialized.get("name", "")
        if tool_name.startswith("transfer_to_"):
            self.handoff_count += 1
            target_agent = tool_name.replace("transfer_to_", "")
            logger.info("Swarm handoff #%d: -> %s", self.handoff_count, target_agent)


__all__ = [
    "is_langsmith_enabled",
    "get_langsmith_client",
    "SwarmTracerCallbackHandler",
]
