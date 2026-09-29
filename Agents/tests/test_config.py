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
    assert cfg.vectorstore.mem0.api_key_env == "MEM0_API_KEY"
    assert cfg.vectorstore.mem0.infer is False


def test_env_overrides_file_defaults() -> None:
    settings, _ = load_merged_settings()
    assert settings.retrieve_k >= 1
    env = Settings(max_tokens=4096)
    overridden = env.model_copy(update={"max_tokens": env.max_tokens})
    assert overridden.max_tokens == 4096


def test_bge_radeon_profile_sets_int8_sqlite_and_llama_gpu() -> None:
    from pathlib import Path

    from swarm_sdk.config.loader import settings_from_file

    profile = Path(__file__).resolve().parents[2] / "Main" / "config" / "swarm-bge-m3-radeon.yaml"
    cfg = load_swarm_config(profile)
    settings = settings_from_file(cfg)
    assert settings.embed_backend == "llama-cpp"
    assert settings.embed_dim == 1024
    assert settings.llama_gpu_layers == 99
    assert settings.llama_n_batch == 8
    assert settings.memory_backend == "sqlite-vec"
    assert settings.vector_quantization == "int8"


def test_agent_manifests_and_coordination() -> None:
    root = agents_root()
    manifests = load_all_agent_manifests(root)
    assert len(manifests) == 15
    assert manifests["Refactor"].role == "safe_incremental_refactor"
    assert manifests["Coder"].role == "implement_changes"
    assert manifests["Coder"].name == "Coder"
    assert {t.id for t in manifests["Coder"].tasks} >= {
        "implement_feature",
        "implement_in_files",
        "fix_regression",
        "add_tests",
    }
    assert manifests["Researcher"].model == "openai:gpt-4o-mini"
    assert validate_coordination(root) == []
