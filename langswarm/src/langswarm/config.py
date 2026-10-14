"""Environment-driven configuration.

All Langswarm settings live under the ``LANGSWARM_`` prefix and are loaded
from the process environment or a local ``.env`` file. LangSmith variables
(``LANGSMITH_*``) are read directly by :mod:`langswarm.observability` because
LangChain consumes them from the environment itself.
"""

__lazy_modules__ = ["pydantic_settings"]

from pydantic_settings import BaseSettings, SettingsConfigDict


class SwarmSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LANGSWARM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    default_model: str = "openai:gpt-4o"
    thread_id: str = "cli-thread"
    config_path: str = "config/swarm.yaml"
    checkpointer: str = "memory"

    log_level: str = "INFO"
    log_json: bool = False

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    vector_backend: str = "faiss"
    faiss_path: str = "data/faiss_index"
    pgvector_connection: str = (
        "postgresql+psycopg://langchain:langchain@localhost:6024/langchain"
    )
    pgvector_collection: str = "langswarm"

    redis_url: str = "redis://localhost:6379"
    data_path: str = "data/sample.csv"

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    grpc_port: int = 50051


settings = SwarmSettings()
