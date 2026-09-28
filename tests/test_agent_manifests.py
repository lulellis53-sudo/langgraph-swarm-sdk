
from swarm_sdk.agents.manifest import agents_root, load_all_agent_manifests
from swarm_sdk.agents.validate import validate_coordination


def test_agent_manifests() -> None:
    manifests = load_all_agent_manifests(agents_root())
    assert len(manifests) == 14
    assert manifests["Refactor"].role == "safe_incremental_refactor"
    assert manifests["Coder"].langgraph_node == "coder"
    assert manifests["Researcher"].model == "openai:gpt-4o-mini"


def test_coordination_matches_manifests() -> None:
    errors = validate_coordination(agents_root())
    assert errors == []
