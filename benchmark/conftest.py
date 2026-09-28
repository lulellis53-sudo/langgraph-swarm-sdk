from pathlib import Path

import pytest
from tests.fakes import Script, ScriptedModel, answer

from swarm_sdk.config import Settings
from swarm_sdk.embeddings import HashEmbedder
from swarm_sdk.rerank import IdentityReranker
from swarm_sdk.swarm import SwarmSDK
from swarm_sdk.yaml_config import load_swarm_config


@pytest.fixture
def bench_settings(tmp_path: Path) -> Settings:
    return Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        max_tokens=512,
    )


@pytest.fixture
def file_config():
    return load_swarm_config(Path("config/swarm.yaml"))


@pytest.fixture
def bench_sdk(bench_settings: Settings, file_config) -> SwarmSDK:
    script = Script(
        [
            answer('{"mode":"swarm","tasks":[]}'),
            answer("bench-answer"),
        ]
    )
    model = ScriptedModel(script=script)
    return SwarmSDK(
        bench_settings,
        file_config=file_config,
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32, model_name="BAAI/bge-small-en-v1.5"),
        reranker=IdentityReranker(),
    )
