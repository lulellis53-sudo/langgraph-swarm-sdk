"""Shared fixtures for the benchmark suite (file config and scripted SDK)."""

from pathlib import Path

import pytest

from benchmark.tests.fakes import Script, ScriptedModel, answer
from swarm_sdk.config.loader import load_swarm_config
from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.rerank import IdentityReranker


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
    return load_swarm_config(Path("Main/config/swarm.yaml"))


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
        embedder=HashEmbedder(32, model_name="sentence-transformers/all-MiniLM-L6-v2"),
        reranker=IdentityReranker(),
    )
