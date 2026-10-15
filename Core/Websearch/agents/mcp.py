"""MCP server: one ``web_search`` tool (the LangChain agent tool).

Run: ``websearch --mcp`` or ``uv run --extra websearch python -m WebSearch.Core.agents.mcp``.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from WebSearch.Core.agents.agent_tools import (
    DEFAULT_LIMIT,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MIN_SCORE,
    search_brief,
)

mcp = MCPServer(
    "WebSearch",
    description="One web_search tool: parallel providers, packed brief for agents.",
)


@mcp.tool()
def web_search(
    query: str,
    limit: int = DEFAULT_LIMIT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    min_score: float = DEFAULT_MIN_SCORE,
) -> str:
    """Search every configured provider and return a token-budgeted brief.

    Args:
        query: Search query (Google dorks work as-is).
        limit: Max hits considered.
        max_tokens: Packer budget (max of tiktoken and Qwen int8 tokenizer).
        min_score: Drop hits whose lexical score is below this (0..1).
    """
    return search_brief(
        query,
        limit=limit,
        max_tokens=max_tokens,
        min_score=min_score,
    )


def main() -> None:
    """Serve the single web_search tool over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
