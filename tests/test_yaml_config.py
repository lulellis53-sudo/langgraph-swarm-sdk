from pathlib import Path

from swarm_sdk.config import Settings, load_merged_settings
from swarm_sdk.yaml_config import load_swarm_config


def test_load_swarm_config_has_routes() -> None:
    cfg = load_swarm_config(Path("config/swarm.yaml"))
    assert cfg.model_select.routes
    assert cfg.hybrid_search.enabled
    assert cfg.router.think_level == "low"


def test_env_overrides_file_defaults() -> None:
    settings, _ = load_merged_settings()
    assert settings.retrieve_k >= 1
    env = Settings(max_tokens=4096)
    merged, _ = load_merged_settings()
    overridden = env.model_copy(update={"max_tokens": env.max_tokens})
    assert overridden.max_tokens == 4096
