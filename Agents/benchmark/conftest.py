"""Shared fixtures for the benchmark suite (file config and scripted SDK)."""

from pathlib import Path

import pytest
from swarm_sdk import vault
from swarm_sdk.config.loader import SwarmFileConfig, load_swarm_config
from swarm_sdk.config.settings import Settings
from swarm_sdk.core.jev_router import JevRouter
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.rerank import IdentityReranker

from benchmark.tests.fakes import Script, ScriptedModel, answer


@pytest.fixture
def bench_settings(tmp_path: Path) -> Settings:
    """Tiny settings (32-dim embeddings, 512-token cap) backed by per-test SQLite files."""
    return Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        max_tokens=512,
    )


@pytest.fixture
def file_config() -> SwarmFileConfig:
    """The packaged ``swarm.yaml``, resolved from the repo root (tests run from there)."""
    return load_swarm_config(Path("Main/config/swarm.yaml"))


@pytest.fixture
def bench_sdk(bench_settings: Settings, file_config: SwarmFileConfig) -> SwarmSDK:
    """SDK with a scripted model: one routing reply, then one swarm answer; no network."""
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


@pytest.fixture(autouse=True)
def _isolate_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep real credentials out of every test.

    Clears each env name the configs reference, blocks the macOS Keychain CLI, hides the
    project ``.env`` and points ``~`` at an empty directory so the legacy ``~/.env``
    fallback finds nothing. Tests that
    need a key set it explicitly (``monkeypatch.setenv`` or an injected vault runner).
    """
    for name in (*vault.referenced_names(), "SWARM_KEYCHAIN_PATH", "KEYS_KEYCHAIN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(vault, "run_cli", lambda argv: None)
    monkeypatch.setattr(vault, "_PROJECT_ENV", tmp_path / "absent.env")
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture(autouse=True)
def _no_hosted_jev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep hosted Jev out of every benchmark test: no endpoint, no key, no vault lookup."""
    for name in ("TYPESAFE_API_KEY", "JEV_API_KEY", "JEV_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("swarm_sdk.vault.get_jev_key", lambda: None)


@pytest.fixture
def local_jev() -> JevRouter:
    """The local deterministic router: no endpoint, no key, no network."""
    return JevRouter(endpoint=None, api_key="")
