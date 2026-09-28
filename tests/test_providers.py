from pathlib import Path

from swarm_sdk.providers import load_provider_catalog
from swarm_sdk.yaml_config import load_swarm_config


def test_load_provider_catalog_yaml() -> None:
    catalog = load_provider_catalog(Path("config/providers.yaml"))
    assert catalog.version == 1
    names = {entry.name for entry in catalog.providers}
    assert names >= {"openai", "anthropic", "groq"}


def test_swarm_config_merges_providers_yaml() -> None:
    cfg = load_swarm_config(Path("config/swarm.yaml"))
    assert len(cfg.providers) >= 3
    assert cfg.providers[0].api_key_env
