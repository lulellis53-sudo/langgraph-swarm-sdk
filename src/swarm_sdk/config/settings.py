"""Runtime settings. Environment variables use the `SWARM_` prefix."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from swarm_sdk.config.loader import SwarmFileConfig

from dotenv import dotenv_values
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

MemoryBackend = Literal["sqlite-vec", "faiss", "qdrant", "opencl", "mem0"]
VectorQuantization = Literal["none", "int8"]
EmbedBackend = Literal["fastembed", "llama-cpp", "hash"]

# API keys live OUTSIDE the repo in ~/.env (never committed). Real environment
# variables always take precedence; empty entries are ignored. Downstream code
# reads provider keys via os.environ (api_key_env in config/model_registry.yaml).
for _env_file in (Path.home() / ".env", Path.cwd() / ".env"):
    try:
        if _env_file.is_file():
            for _key, _value in dotenv_values(_env_file).items():
                if _value and _key not in os.environ:
                    os.environ[_key] = _value
    except (PermissionError, OSError):
        pass


class Settings(BaseSettings):
    """Runtime settings. Environment variables use the `SWARM_` prefix."""

    model_config = SettingsConfigDict(env_prefix="SWARM_", extra="ignore")

    router_model: str = "openai:gpt-4o-mini"
    specialist_model: str = "openai:gpt-4o"
    max_tokens: int = Field(default=2048, ge=1)
    tool_cap: int = Field(default=128, ge=1)
    semantic_threshold: float = Field(default=0.97, ge=0.0, le=1.0)
    dedup_threshold: float = Field(default=0.98, ge=0.0, le=1.0)
    retrieve_k: int = Field(default=20, ge=1)
    rerank_k: int = Field(default=4, ge=1)
    embed_dim: int = Field(default=384, ge=1)
    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    memory_backend: MemoryBackend = "sqlite-vec"
    memory_path: str = "swarm.sqlite"
    # Mem0 Platform: env var *name* only. Value lives in ~/.env as MEM0_API_KEY.
    mem0_api_key_env: str = "MEM0_API_KEY"
    mem0_user_id: str = "swarm"
    mem0_agent_id: str = "swarm-sdk"
    mem0_infer: bool = False
    cache_path: str = "swarm-cache.sqlite"
    peer_url: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    grpc_port: int = 50051
    embed_batch_size: int = Field(default=64, ge=1)
    hybrid_enabled: bool = True
    # FAISS GPU is CUDA-only. AMD Radeon / MoltenVK / OpenCL cannot host this index.
    vector_gpu: bool = False
    vector_quantization: VectorQuantization = "none"
    # GPU acceleration options for Intel Mac + Radeon Pro 5300M
    embed_backend: EmbedBackend = "fastembed"
    llama_embed_model: str | None = None
    llama_gpu_layers: int = Field(default=0, ge=0)
    llama_n_ctx: int = Field(default=2048, ge=1)
    llama_n_batch: int = Field(default=8, ge=1)
    opencl_enabled: bool = True
    opencl_quantize: Literal["none", "int8", "binary"] = "none"
    semantic_cache_on_gpu: bool = False
    cache_ttl_days: int | None = Field(default=None, ge=1)
    router_structured_output: bool = True


def load_merged_settings(
    config_path: Path | None = None,
) -> tuple[Settings, SwarmFileConfig]:
    from swarm_sdk.config.loader import load_settings

    return load_settings(config_path)


__all__ = [
    "EmbedBackend",
    "MemoryBackend",
    "Settings",
    "VectorQuantization",
    "load_merged_settings",
]
