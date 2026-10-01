"""Config loading, YAML routes, and agent manifest validation."""

from __future__ import annotations

from pathlib import Path

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

    profile = Path(__file__).resolve().parents[3] / "Main" / "config" / "swarm-bge-m3-radeon.yaml"
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
    assert len(manifests) >= 15
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


def test_new_settings_defaults_preserve_behavior() -> None:
    s = Settings()
    assert s.opencl_quantize == "none"
    assert s.semantic_cache_on_gpu is False
    assert s.cache_ttl_days is None
    assert s.router_structured_output is True


def test_file_config_maps_quantize_and_structured_output(tmp_path: Path) -> None:
    from swarm_sdk.config.loader import load_settings

    cfg = tmp_path / "s.yaml"
    cfg.write_text(
        "version: 1\nvectorstore:\n  backend: opencl\n  quantize: int8\n"
        "router:\n  structured_output: false\n",
        encoding="utf-8",
    )
    settings, file_cfg = load_settings(cfg)
    assert file_cfg.vectorstore.quantize == "int8"
    assert settings.opencl_quantize == "int8"
    assert settings.router_structured_output is False


def test_environment_backend_overrides_file_config(tmp_path: Path, monkeypatch) -> None:
    from swarm_sdk.config.loader import load_settings

    config = tmp_path / "swarm.yaml"
    config.write_text("version: 1\nvectorstore:\n  backend: sqlite-vec\n", encoding="utf-8")
    monkeypatch.setenv("SWARM_MEMORY_BACKEND", "mem0")

    settings, _ = load_settings(config)

    assert settings.memory_backend == "mem0"


def test_coordination_rejects_unregistered_task_assignee(tmp_path: Path) -> None:
    agents_dir = tmp_path / "Agents"
    tester_dir = agents_dir / "Tester"
    tester_dir.mkdir(parents=True)
    (tester_dir / "agent.yaml").write_text(
        "version: 1\nname: Tester\nrole: test\ntasks:\n  - id: run_tests\n"
        "    description: Run tests\n",
        encoding="utf-8",
    )
    (agents_dir / "coordination.yaml").write_text(
        "version: '1'\nagents:\n  - name: Tester\n    manifest: Agents/Tester/agent.yaml\n"
        "tasks:\n  - id: T01\n    assigned: [Tester/Nested]\n    task: run_tests\n",
        encoding="utf-8",
    )

    errors = validate_coordination(agents_dir)

    assert errors == ["T01: unknown assigned agent 'Tester/Nested'"]


def test_open_store_passes_quantize_to_opencl_store() -> None:
    from swarm_sdk.core.swarm import open_store

    store = open_store(Settings(memory_backend="opencl", embed_dim=64, opencl_quantize="binary"))
    assert getattr(store, "_mode") == "binary"


def test_bundled_yaml_still_loads_and_defaults_unchanged() -> None:
    cfg = load_swarm_config()
    assert cfg.vectorstore.quantize == "none"
    assert cfg.router.structured_output is True
