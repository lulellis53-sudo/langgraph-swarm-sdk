"""Offline LangGraph swarm assembly tests; model calls are never made."""

from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from langswarm import providers
from langswarm.blueprint import load_blueprint
from langswarm.swarm import build_from_blueprint


def test_swarm_compilation(monkeypatch) -> None:
    monkeypatch.setattr(
        providers, "build_model", lambda model_id="": FakeListChatModel(responses=["done"])
    )
    config_path = Path(__file__).parents[1] / "config" / "swarm.yaml"
    swarm = build_from_blueprint(load_blueprint(config_path))
    nodes = set(swarm.get_graph().nodes)
    assert {"Router", "Coder", "Researcher", "Davinci", "Finisher"} <= nodes
