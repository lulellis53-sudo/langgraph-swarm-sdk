"""Config loading, YAML routes, and agent manifest validation."""

from __future__ import annotations

from swarm_sdk.agents.manifest import agents_root, load_all_agent_manifests
from swarm_sdk.agents.validate import validate_coordination
from swarm_sdk.config.loader import load_swarm_config
from swarm_sdk.config.settings import Settings, load_merged_settings


def test_load_swarm_config_defaults() -> None:
    cfg = load_swarm_config()
    assert cfg.model_select.routes
    assert cfg.hybrid_search.enabled
    assert cfg.router.think_level == "low"
    assert cfg.vectorstore.opencl_enabled is True
    assert cfg.embedding.quantization == "int8"
    assert cfg.vectorstore.quantization == "int8"
    assert cfg.embedding.model == "sentence-transformers/all-MiniLM-L6-v2"


def test_env_overrides_file_defaults() -> None:
    settings, _ = load_merged_settings()
    assert settings.retrieve_k >= 1
    env = Settings(max_tokens=4096)
    overridden = env.model_copy(update={"max_tokens": env.max_tokens})
    assert overridden.max_tokens == 4096


def test_agent_manifests_and_coordination() -> None:
    root = agents_root()
    manifests = load_all_agent_manifests(root)
    assert len(manifests) == 15
    assert manifests["Refactor"].role == "safe_incremental_refactor"
    assert manifests["Coder"].role == "implement_changes"
    assert manifests["Coder"].name == "Coder"
    assert manifests["Researcher"].model == "openai:gpt-4o-mini"
    assert validate_coordination(root) == []
