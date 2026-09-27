from pathlib import Path

from langchain_core.messages import AIMessage
from tests.fakes import Script, ScriptedModel, answer

from swarm_sdk.cache import SemanticCache
from swarm_sdk.config import Settings
from swarm_sdk.embeddings import HashEmbedder
from swarm_sdk.rerank import IdentityReranker
from swarm_sdk.swarm import SwarmSDK


class SpyEmbedder:
    def __init__(self, inner: HashEmbedder) -> None:
        self.inner = inner
        self.calls = 0
        self.dim = inner.dim

    def embed(self, texts: list[str]):
        self.calls += 1
        return self.inner.embed(texts)


def _sdk(tmp_path: Path, script: Script, embedder: SpyEmbedder) -> tuple[SwarmSDK, ScriptedModel]:
    model = ScriptedModel(script=script)
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        max_tokens=256,
    )
    sdk = SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=embedder,
        reranker=IdentityReranker(),
        cache=SemanticCache(settings.cache_path, embedder, threshold=0.97),
    )
    return sdk, model


async def test_exact_cache_hit_does_not_call_the_model(tmp_path: Path) -> None:
    embedder = SpyEmbedder(HashEmbedder(dim=32))
    script = Script(
        [
            AIMessage(content='{"mode":"swarm","tasks":[]}'),
            answer("from-model"),
        ]
    )
    sdk, model = _sdk(tmp_path, script, embedder)
    first = await sdk.run("Hello", "thread-1")
    calls = model.script.calls
    embeds = embedder.calls
    second = await sdk.run("hello", "thread-1")
    assert first.text == "from-model"
    assert first.cached is False
    assert second.cached is True
    assert second.text == "from-model"
    assert model.script.calls == calls
    assert embedder.calls == embeds


async def test_semantic_cache_hit_does_not_call_the_model(tmp_path: Path) -> None:
    embedder = SpyEmbedder(HashEmbedder(dim=32))
    script = Script(
        [
            AIMessage(content='{"mode":"swarm","tasks":[]}'),
            answer("semantic-answer"),
        ]
    )
    sdk, model = _sdk(tmp_path, script, embedder)
    await sdk.run("topic: one", "thread-a")
    calls = model.script.calls
    second = await sdk.run("topic: two", "thread-b")
    assert second.cached is True
    assert second.text == "semantic-answer"
    assert model.script.calls == calls
