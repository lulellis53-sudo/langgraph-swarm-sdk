"""Config loading, YAML routes, and agent manifest validation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from swarm_sdk.agents.manifest import agents_root, load_all_agent_manifests
from swarm_sdk.agents.validate import validate_coordination
from swarm_sdk.config.loader import _BUNDLED_SWARM_CONFIG, load_swarm_config
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
    assert manifests["Researcher"].model == "openai:gpt-6-luna"
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


def test_environment_backend_overrides_file_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
_SECRET_SHAPE = re.compile(
    r"(sk|tp|ttp|xai|gsk|pk)-[A-Za-z0-9_-]{16,}|AQ\.[A-Za-z0-9_-]{20,}|[A-Za-z0-9+/_-]{40,}"
)
_SECRET_KEYS = ("api_key", "apikey", "token", "secret", "password")
_ENV_REF = re.compile(r"\$\{[A-Z][A-Z0-9_]*(:?[?-][^}]*)?\}")  # compose substitution
_NOT_SECRETS = {"id-token"}  # GitHub OIDC permission, value is read/write


def _yaml_files() -> list[Path]:
    root = agents_root().parent
    skip = {".venv", "node_modules", ".git"}
    return [
        p for p in root.rglob("*.y*ml") if p.suffix in {".yaml", ".yml"} and not skip & set(p.parts)
    ]


def _secret_findings(node: object, trail: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{trail}.{key}"
            if str(key).endswith("_env"):
                if value is not None and not (
                    isinstance(value, str) and _ENV_NAME.fullmatch(value)
                ):
                    found.append(f"{here}: not an env-var name")
            elif (
                any(s in str(key).lower() for s in _SECRET_KEYS)
                and str(key) not in _NOT_SECRETS
                and isinstance(value, str)
                and value
                and not _ENV_REF.fullmatch(value)
            ):
                found.append(f"{here}: holds a value, use an *_env name")
            else:
                found.extend(_secret_findings(value, here))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            found.extend(_secret_findings(item, f"{trail}[{i}]"))
    elif isinstance(node, str) and _SECRET_SHAPE.fullmatch(node):
        found.append(f"{trail}: looks like a secret")
    return found


def test_yaml_never_holds_secret_values() -> None:
    files = _yaml_files()
    assert files, "no YAML found; scan root is wrong"
    problems = [
        f"{path}: {finding}"  # path and location only, never the value
        for path in files
        for finding in _secret_findings(yaml.safe_load(path.read_text()))
    ]
    assert not problems, "\n".join(problems)


def test_agent_models_use_registered_credential_names() -> None:
    from swarm_sdk.models.registry import load_registry

    routes = {entry.name: entry.api_key_env for entry in load_registry().providers}
    agents_dir = agents_root()
    for path in agents_dir.rglob("agent.yaml"):
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        model = manifest.get("model")
        if model in (None, "inherit"):
            continue
        assert model in routes, f"{path}: model is not registered"
        assert manifest.get("api_key_env") == routes[model], (
            f"{path}: api_key_env differs from the registered model"
        )


def test_service_credentials_have_agents_and_are_primed() -> None:
    from swarm_sdk.vault import referenced_names

    registry_path = agents_root().parent / "Main/config/model_registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    services = registry["services"]
    assert {service["api_key_env"] for service in services} == {
        "APIFY_API_KEY",
        "BRAVE_API_KEY",
        "BRIGHTDATA_MCP_TOKEN",
        "EXA_API_KEY",
        "JEV_API_KEY",
        "JINA_API_KEY",
        "MEM0_API_KEY",
        "TAVILY_API_KEY",
    }
    agents = load_all_agent_manifests()
    assert all(
        service["agents"] and set(service["agents"]) <= agents.keys() for service in services
    )
    configured = {
        entry["api_key_env"]
        for entry in [*registry["providers"], *services]
        if "api_key_env" in entry
    }
    assert configured <= set(referenced_names())


def test_secret_scan_flags_values_without_echoing_them() -> None:
    bad = {"api_key": "sk-abcdefghijklmnopqrstuvwx", "x": {"api_key_env": "not a name"}}
    out = _secret_findings(bad)
    assert len(out) == 2 and not any("abcdefgh" in line for line in out)


def test_dotenv_is_owner_only_when_present() -> None:
    env = agents_root().parent / ".env"
    if env.exists():
        assert env.stat().st_mode & 0o077 == 0, ".env must be chmod 600"


def test_load_provider_catalog_parses_bundled_yaml() -> None:
    from swarm_sdk.config.loader import load_provider_catalog

    catalog = load_provider_catalog(_BUNDLED_SWARM_CONFIG.parent / "providers.yaml")

    assert catalog.providers
    codex_entry = next(p for p in catalog.providers if p.name == "codex")
    assert codex_entry.api_key_env == "CODEX_OAUTH_TOKEN"
    assert catalog.ranked()[0].priority <= catalog.ranked()[-1].priority


def test_load_provider_catalog_rejects_non_mapping(tmp_path: Path) -> None:
    from swarm_sdk.config.loader import load_provider_catalog

    bad = tmp_path / "providers.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a mapping"):
        load_provider_catalog(bad)
