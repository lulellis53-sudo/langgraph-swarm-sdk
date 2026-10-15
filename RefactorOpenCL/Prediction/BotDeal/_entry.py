"""CLI and MCP entrypoints for the BotDeal lane."""

from __future__ import annotations


def run_harvest() -> int:
    """Run the WebSearch-backed price harvest (``python -m Prediction.harvest``)."""
    from Prediction.harvest import main

    return main()


def mcp_main() -> None:
    """Start the PromoDeals MCP server (stdio)."""
    from Prediction.mcp_server import mcp

    mcp.run()
