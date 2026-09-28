from pathlib import Path

import pytest
from tests.fakes import Script, ScriptedModel, answer

from swarm_sdk.config import Settings
from swarm_sdk.embeddings import HashEmbedder
from swarm_sdk.rerank import IdentityReranker
from swarm_sdk.swarm import SwarmSDK
from swarm_sdk.yaml_config import load_swarm_config


@pytest.mark.asyncio
async def test_parallel_fanout(tmp_path: Path) -> None:
    router = ScriptedModel(
        script=Script([answer('{"mode":"parallel","tasks":["alpha","beta"]}')])
    )
    specialist_script = Script([answer("ok")] * 4)
    specialist = ScriptedModel(script=specialist_script)
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
    )
    sdk = SwarmSDK(
        settings,
        file_config=load_swarm_config(),
        router_model=router,
        specialist_model=specialist,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
    )
    result = await sdk.run("parallel benchmark", "pf")
    assert result.mode == "parallel"
    assert result.active_agent == "synthesizer"
