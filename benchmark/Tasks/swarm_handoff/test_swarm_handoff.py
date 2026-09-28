from pathlib import Path

import pytest
from tests.fakes import Script, ScriptedModel, answer, handoff

from swarm_sdk.config import Settings
from swarm_sdk.embeddings import HashEmbedder
from swarm_sdk.memory.sqlite_vec import SqliteVecStore
from swarm_sdk.rerank import IdentityReranker
from swarm_sdk.swarm import SwarmSDK
from swarm_sdk.yaml_config import load_swarm_config


@pytest.mark.asyncio
async def test_swarm_handoff(tmp_path: Path) -> None:
    router = ScriptedModel(script=Script([answer('{"mode":"swarm","tasks":[]}')]))
    specialist = ScriptedModel(
        script=Script([handoff("coder"), answer("patched"), answer("done")])
    )
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
        memory=SqliteVecStore(settings.memory_path, 32),
    )
    first = await sdk.run("code please", "bench-handoff")
    assert first.active_agent == "coder"
    assert first.text == "patched"
