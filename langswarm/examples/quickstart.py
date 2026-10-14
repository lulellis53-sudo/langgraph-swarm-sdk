"""Quickstart example demonstrating LangSwarm programmatic setup and execution."""

from __future__ import annotations

import asyncio
from pathlib import Path

from langswarm.blueprint import load_blueprint
from langswarm.runner import run_turn
from langswarm.swarm import compile_swarm_from_blueprint


async def main() -> None:
    """Run a sample conversation turn with LangSwarm."""
    blueprint_path = Path(__file__).parent.parent / "config" / "swarm.yaml"
    blueprint = load_blueprint(blueprint_path)

    # Compile the 12-agent LangGraph swarm
    swarm = compile_swarm_from_blueprint(blueprint)

    # Run a simple query
    query = "Inspect the sample dataset and compute 2**10"
    print(f"User: {query}\n")

    response = await run_turn(swarm, query, thread_id="quickstart-session")
    print(f"\nFinal Swarm Response:\n{response}")


if __name__ == "__main__":
    asyncio.run(main())
