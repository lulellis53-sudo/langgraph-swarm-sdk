"""API freeze: names other modules and tests import from swarm_sdk.core.swarm."""

import swarm_sdk.core.swarm as swarm

PUBLIC = [
    "CODER_PROMPT",
    "CompiledGraph",
    "REVIEWER_PROMPT",
    "ROUTER_SYSTEM",
    "RESEARCHER_PROMPT",
    "RouteDecision",
    "RunResult",
    "SwarmSDK",
    "_websearch_tools",  # tests patch this by dotted path, so it must stay defined here
    "default_embedder",
    "default_reranker",
    "manifest_node_prompt",
    "open_store",
]


def test_names_survive_the_split() -> None:
    assert [name for name in PUBLIC if not hasattr(swarm, name)] == []


def test_all_is_importable() -> None:
    assert [name for name in swarm.__all__ if not hasattr(swarm, name)] == []
