"""Parametric routing checks shared with the jev_agent_routing benchmark."""

from __future__ import annotations

import pytest
from Core.benchmark.tasks.jev_agent_routing.cases import (
    AGENT_ROUTING_CASES,
    SWARM_AGENT_CANDIDATES,
)

from swarm_sdk.core.jev_router import JevRouter


@pytest.mark.parametrize(("goal", "expected_agent"), AGENT_ROUTING_CASES)
def test_swarm_agent_choice_routing(goal: str, expected_agent: str) -> None:
    """Each golden goal must route to the labeled specialist (local Jev fallback)."""
    router = JevRouter(endpoint=None, api_key="")
    decision = router.evaluate_choice(goal, list(SWARM_AGENT_CANDIDATES))
    assert decision.selected_choice == expected_agent
