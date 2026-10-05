"""Runtime settings. Environment variables use the `SWARM_` prefix."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from swarm_sdk.config.loader import SwarmFileConfig

from dotenv import dotenv_values
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

MemoryBackend = Literal["sqlite-vec", "faiss", "qdrant", "opencl", "mem0"]
VectorQuantization = Literal["none", "int8"]
EmbedBackend = Literal["fastembed", "llama-cpp", "llama-server", "hash"]

# API keys live OUTSIDE the repo in ~/.env (never committed). Real environment
# variables always take precedence; empty entries are ignored. Downstream code
# reads provider keys via os.environ (api_key_env in config/model_registry.yaml).
for _env_file in (Path.home() / ".env", Path.cwd() / ".env"):
    try:
        if _env_file.is_file():
            for _key, _value in dotenv_values(_env_file).items():
                if _value and _key not in os.environ:
                    os.environ[_key] = _value
    except PermissionError, OSError:
        pass


class Settings(BaseSettings):
    """Runtime settings. Environment variables use the `SWARM_` prefix."""

    model_config = SettingsConfigDict(env_prefix="SWARM_", extra="ignore")

    router_model: str = "openai:gpt-6-luna"
    specialist_model: str = "anthropic:claude-sonnet-4.6"
    max_tokens: int = Field(default=2048, ge=1)
    # Hard cap on graph steps per run; a handoff ping-pong stops here (spec §17.1/§17.5).
    recursion_limit: int = Field(default=50, ge=2)
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
    # Optional shared exact-response cache; unset keeps caching local to SQLite.
    redis_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REDIS_URL", "SWARM_REDIS_URL", "redis_url"),
    )
    redis_cache_ttl_s: int = Field(default=86400, ge=1)
    # None keeps checkpoints in memory (lost on restart); a path makes threads durable.
    checkpoint_path: str | None = None
    peer_url: str | None = None
    # LangGraph Server deployment (langgraph.json): when set, runs delegate to the
    # server via langgraph_sdk instead of running the graph in-process.
    server_url: str | None = None
    server_graph: str = "swarm"
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
    llama_server_url: str = "http://127.0.0.1:8080"
    opencl_enabled: bool = True
    opencl_quantize: Literal["none", "int8", "binary"] = "none"
    semantic_cache_on_gpu: bool = False
    cache_ttl_days: int | None = Field(default=None, ge=1)
    router_structured_output: bool = True
    # Plan decomposition via tool-calling structured output; off = JSON prompt + regex.
    planner_structured_output: bool = True
    # Give manifest agents with the ``web_search`` capability the WebSearch LangChain
    # tools. Off keeps runs offline and deterministic (tests, CI).
    enable_websearch_tools: bool = False
    # Token-saving context middleware on every swarm agent node. Context editing
    # clears old tool uses (handoff results, tool outputs) from the replayed
    # transcript once it passes ``swarm_edit_trigger_tokens`` approximate tokens;
    # it makes no model calls.
    swarm_context_editing: bool = True
    swarm_edit_trigger_tokens: int = Field(default=2048, ge=1)
    # Most recent tool uses kept verbatim when the edit fires; older ones become
    # the ``[cleared]`` placeholder.
    swarm_edit_keep_tool_uses: int = Field(default=3, ge=0)
    # Summarization replaces the old transcript with a model-written summary past
    # twice the edit trigger. Off by default: it spends an extra model call per
    # trigger and is not offline-deterministic.
    swarm_summarization: bool = False
    # JEV System-1 routing: use the non-autoregressive semantic router to pick the
    # entry agent and workflow mode instead of the LLM router / static defaults.
    jev_routing: bool = False
    jev_endpoint: str | None = None
    jev_timeout_s: float = Field(default=0.030, ge=0.001)


def load_merged_settings(
    config_path: Path | None = None,
) -> tuple[Settings, SwarmFileConfig]:
    """Load settings from environment variables merged over the packaged ``swarm.yaml`` defaults."""
    from swarm_sdk.config.loader import load_settings

    return load_settings(config_path)


__all__ = [
    "EmbedBackend",
    "MemoryBackend",
    "Settings",
    "VectorQuantization",
    "load_merged_settings",
]
