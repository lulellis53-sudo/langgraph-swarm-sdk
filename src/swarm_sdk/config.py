from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

MemoryBackend = Literal["sqlite-vec", "faiss", "qdrant"]


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
    embed_model: str = "BAAI/bge-small-en-v1.5"
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    memory_backend: MemoryBackend = "sqlite-vec"
    memory_path: str = "swarm.sqlite"
    cache_path: str = "swarm-cache.sqlite"
    peer_url: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    grpc_port: int = 50051
