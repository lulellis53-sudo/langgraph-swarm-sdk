"""LangChain Agent Middleware.

Provides context editing, prompt compression, and history summarization
middleware to control token budgets across long-running multi-agent swarms.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_default_middleware(
    *,
    context_editing: bool = True,
    summarization: bool = False,
    trigger_tokens: int = 4000,
    keep_tool_uses: int = 3,
    summary_model: Any | None = None,
) -> list[Any]:
    """Construct a pipeline of LangChain middleware for swarm agents.

    Args:
        context_editing: If True, attach ClearToolUsesEdit to prune stale tool outputs.
        summarization: If True, attach SummarizationMiddleware to compress older turns.
        trigger_tokens: Token ceiling that activates context editing.
        keep_tool_uses: Number of recent tool calls/outputs to retain.
        summary_model: Optional chat model used to synthesize history summaries.

    Returns:
        List of configured LangChain agent middleware instances.
    """
    middleware: list[Any] = []

    if context_editing:
        try:
            from langchain.agents.middleware import ContextEditingMiddleware
            from langchain.agents.middleware.context_editing import ClearToolUsesEdit

            middleware.append(
                ContextEditingMiddleware(
                    edits=[
                        ClearToolUsesEdit(
                            trigger=trigger_tokens,
                            keep=keep_tool_uses,
                        )
                    ]
                )
            )
        except (ImportError, AttributeError) as exc:
            logger.debug("ContextEditingMiddleware not available in this environment: %s", exc)

    if summarization and summary_model is not None:
        try:
            from langchain.agents.middleware import SummarizationMiddleware

            middleware.append(
                SummarizationMiddleware(
                    model=summary_model,
                    trigger=("tokens", trigger_tokens * 2),
                    keep=("messages", 6),
                )
            )
        except (ImportError, AttributeError) as exc:
            logger.debug("SummarizationMiddleware not available in this environment: %s", exc)

    return middleware


__all__ = ["build_default_middleware"]
