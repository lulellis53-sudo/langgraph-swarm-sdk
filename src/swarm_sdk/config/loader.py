"""Load swarm.yaml and merge with environment-backed Settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, cast

import yaml
from pydantic import BaseModel, Field

from swarm_sdk.config.settings import EmbedBackend, MemoryBackend, Settings, VectorQuantization
from swarm_sdk.models.breaker import BreakerConfig
from swarm_sdk.models.selection import ModelRoute, ModelSelectConfig, ThinkLevel
from swarm_sdk.retrieval.gate import GateConfig
from swarm_sdk.retrieval.hybrid import HybridSearchConfig


class ParallelismConfig(BaseModel):
    """Wave concurrency limits (the ``parallelism:`` block)."""

    max_concurrency: int = Field(default=8, ge=1)
    task_queue_size: int = 128
    synth_timeout_s: int = 60


class ProviderEntry(BaseModel):
    """One provider row from ``providers.yaml``."""

    name: str
    models: list[str] = Field(default_factory=list)
    api_key_env: str = ""
    priority: int = 100


class ProviderCatalog(BaseModel):
    """Parsed ``providers.yaml`` (the file beside ``swarm.yaml``)."""

    version: int = 1
    providers: list[ProviderEntry] = Field(default_factory=list)

    def ranked(self) -> list[ProviderEntry]:
        """Entries sorted by priority (lower = preferred)."""
        return sorted(self.providers, key=lambda entry: entry.priority)


def load_provider_catalog(path: Path) -> ProviderCatalog:
    """Parse a ``providers.yaml`` file into a :class:`ProviderCatalog`.

    Args:
        path: Explicit path to the providers file.

    Returns:
        Parsed catalog; ``providers`` is empty when the file lists none.

    Raises:
        ValueError: If the file is not a YAML mapping.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"providers file must be a mapping: {path}")
    return ProviderCatalog.model_validate(data)


class EmbeddingConfig(BaseModel):
    """Embedding model and batching configuration."""

    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    dim: int = 384
    batch_size: int = 64
    normalize: bool = True
    dedup_threshold: float = 0.98
    # FastEmbed ships MiniLM-L6-v2 as ONNX INT8. Not a GPU flag.
    quantization: str = "int8"
    # fastembed | llama-cpp | llama-server | hash
    backend: EmbedBackend = "fastembed"
    llama_model: str | None = None
    llama_gpu_layers: int = Field(default=0, ge=0)
    llama_n_ctx: int = Field(default=2048, ge=1)
    llama_n_batch: int = Field(default=8, ge=1)
    llama_server_url: str = "http://127.0.0.1:8080"


class QdrantStoreConfig(BaseModel):
    """Remote Qdrant connection settings."""

    url_env: str = "QDRANT_URL"
    collection: str = "swarm_memory"


class Mem0StoreConfig(BaseModel):
    """Hosted Mem0 Platform adapter (``vectorstore.backend: mem0``)."""

    api_key_env: str = "MEM0_API_KEY"
    user_id: str = "swarm"
    agent_id: str = "swarm-sdk"
    infer: bool = False


class VectorStoreConfig(BaseModel):
    """Vector-store backend selection and store-specific settings."""

    backend: MemoryBackend = "sqlite-vec"
    path: str = "swarm.sqlite"
    retrieve_k: int = 20
    final_k: int = 10
    # CUDA FAISS only. Ignored on machines without faiss-gpu (including Radeon 5300).
    gpu: bool = False
    quantization: VectorQuantization = "int8"
    # Allow disabling OpenCL offloading without uninstalling pyopencl.
    opencl_enabled: bool = True
    # OpenClVecStore precision: float32, per-row INT8, or 1-bit signs.
    quantize: Literal["none", "int8", "binary"] = "none"
    qdrant: QdrantStoreConfig = Field(default_factory=QdrantStoreConfig)
    mem0: Mem0StoreConfig = Field(default_factory=Mem0StoreConfig)


class RerankConfig(BaseModel):
    """Reranker model configuration."""

    model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    top_k: int = 4


class RagConfig(BaseModel):
    """Opt-in RAG techniques; every flag defaults to the previous behavior."""

    u_shape_order: bool = False
    parent_child: bool = False
    child_size: int = Field(default=400, ge=1)
    gate: GateConfig = Field(default_factory=GateConfig)


class RouterConfig(BaseModel):
    """Router model selection (think level)."""

    router_model: str = "openai:gpt-6-luna"
    think_level: ThinkLevel = "low"
    max_tokens: int = 2048
    tool_cap: int = 128
    # Ask the provider for JSON output; parsing still falls back to regex.
    structured_output: bool = True


# Packaged default (also overridable via Main/config/swarm.yaml or SWARM_CONFIG_PATH).
_BUNDLED_SWARM_CONFIG = Path(__file__).resolve().parent.parent / "agents" / "config" / "swarm.yaml"


class SwarmFileConfig(BaseModel):
    """Parsed ``swarm.yaml``: providers, routes, parallelism, stores."""

    version: int = 1
    parallelism: ParallelismConfig = Field(default_factory=ParallelismConfig)
    providers: list[ProviderEntry] = Field(default_factory=list)
    model_select: ModelSelectConfig = Field(default_factory=ModelSelectConfig)
    circuit_breaker: BreakerConfig = Field(default_factory=BreakerConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    vectorstore: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    hybrid_search: HybridSearchConfig = Field(default_factory=HybridSearchConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)


def default_config_path() -> Path:
    """Resolve config by env override, Main/config, cwd, parent, then package default."""
    env = os.environ.get("SWARM_CONFIG_PATH")
    if env:
        return Path(env)
    cwd = Path.cwd()
    candidates = [
        cwd / "Main" / "config" / "swarm.yaml",
        (cwd / ".." / "Main" / "config" / "swarm.yaml").resolve(),
        cwd / "config" / "swarm.yaml",
        (cwd / ".." / "config" / "swarm.yaml").resolve(),
        _BUNDLED_SWARM_CONFIG,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return _BUNDLED_SWARM_CONFIG


def _parse_routes(raw: object) -> list[ModelRoute]:
    if not isinstance(raw, dict):
        return []
    routes_raw = raw.get("routes", [])
    if not isinstance(routes_raw, list):
        return []
    routes: list[ModelRoute] = []
    for item in routes_raw:
        if not isinstance(item, dict):
            continue
        levels = item.get("think_levels", [])
        if isinstance(levels, list):
            think_levels = cast(
                tuple[ThinkLevel, ...],
                tuple(str(x) for x in levels),
            )
        else:
            think_levels = ("medium",)
        routes.append(
            ModelRoute(
                name=str(item["name"]),
                provider=str(item.get("provider", "openai")),
                think_levels=think_levels,
                priority=int(item.get("priority", 100)),
            )
        )
    return routes


def load_swarm_config(path: Path | None = None) -> SwarmFileConfig:
    """Load and validate ``swarm.yaml`` (packaged default or explicit path).

    Args:
    path: Explicit config path; defaults to the packaged swarm.yaml.

    Returns:
    The parsed file configuration.

    Raises:
    ValueError: If the file is not a YAML mapping.

    """
    cfg_path = path or default_config_path()
    if not cfg_path.is_file():
        return SwarmFileConfig()
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"config must be a mapping: {cfg_path}")

    model_raw = data.get("model_select", {})
    default_level = "medium"
    if isinstance(model_raw, dict) and "default_level" in model_raw:
        default_level = str(model_raw["default_level"])

    hybrid_raw = data.get("hybrid_search", {})
    if isinstance(hybrid_raw, dict):
        hybrid = HybridSearchConfig.model_validate(hybrid_raw)
    else:
        hybrid = HybridSearchConfig()
    vector_raw = data.get("vectorstore", {})
    final_k = hybrid.final_k
    if isinstance(vector_raw, dict) and "final_k" in vector_raw:
        final_k = int(vector_raw["final_k"])
        hybrid = hybrid.model_copy(update={"final_k": final_k})

    providers_path = cfg_path.parent / "providers.yaml"
    if providers_path.is_file():
        providers = load_provider_catalog(providers_path).providers
    else:
        providers = [
            ProviderEntry.model_validate(p)
            for p in data.get("providers", [])
            if isinstance(p, dict)
        ]

    return SwarmFileConfig(
        version=int(data.get("version", 1)),
        parallelism=ParallelismConfig.model_validate(data.get("parallelism", {})),
        providers=providers,
        model_select=ModelSelectConfig(
            default_level=cast(ThinkLevel, default_level),
            routes=_parse_routes(model_raw),
        ),
        circuit_breaker=BreakerConfig.model_validate(data.get("circuit_breaker", {})),
        embedding=EmbeddingConfig.model_validate(data.get("embedding", {})),
        vectorstore=VectorStoreConfig.model_validate(data.get("vectorstore", {})),
        hybrid_search=hybrid,
        rerank=RerankConfig.model_validate(data.get("rerank", {})),
        rag=RagConfig.model_validate(data.get("rag", {})),
        router=RouterConfig.model_validate(data.get("router", {})),
    )


def settings_from_file(file_cfg: SwarmFileConfig, env: Settings | None = None) -> Settings:
    """Merge file defaults under explicitly supplied runtime settings."""
    base = env or Settings()
    updates: dict[str, object] = {
        "router_model": file_cfg.router.router_model,
        "max_tokens": file_cfg.router.max_tokens,
        "tool_cap": file_cfg.router.tool_cap,
        "dedup_threshold": file_cfg.embedding.dedup_threshold,
        "retrieve_k": file_cfg.vectorstore.retrieve_k,
        "rerank_k": file_cfg.rerank.top_k,
        "embed_dim": file_cfg.embedding.dim,
        "embed_model": file_cfg.embedding.model,
        "embed_backend": file_cfg.embedding.backend,
        "llama_embed_model": file_cfg.embedding.llama_model,
        "llama_gpu_layers": file_cfg.embedding.llama_gpu_layers,
        "llama_n_ctx": file_cfg.embedding.llama_n_ctx,
        "llama_n_batch": file_cfg.embedding.llama_n_batch,
        "llama_server_url": file_cfg.embedding.llama_server_url,
        "rerank_model": file_cfg.rerank.model,
        "memory_backend": file_cfg.vectorstore.backend,
        "memory_path": file_cfg.vectorstore.path,
        "mem0_api_key_env": file_cfg.vectorstore.mem0.api_key_env,
        "mem0_user_id": file_cfg.vectorstore.mem0.user_id,
        "mem0_agent_id": file_cfg.vectorstore.mem0.agent_id,
        "mem0_infer": file_cfg.vectorstore.mem0.infer,
        "embed_batch_size": file_cfg.embedding.batch_size,
        "hybrid_enabled": file_cfg.hybrid_search.enabled,
        "vector_gpu": file_cfg.vectorstore.gpu,
        "vector_quantization": file_cfg.vectorstore.quantization,
        "opencl_enabled": file_cfg.vectorstore.opencl_enabled,
        "opencl_quantize": file_cfg.vectorstore.quantize,
        "router_structured_output": file_cfg.router.structured_output,
    }
    if file_cfg.model_select.routes:
        strong = next(
            (r.name for r in file_cfg.model_select.routes if r.name.startswith("anthropic:claude")),
            None,
        )
        if strong is None:
            strong = next(
                (
                    r.name
                    for r in file_cfg.model_select.routes
                    if "gpt-4o" in r.name and "mini" not in r.name
                ),
                None,
            )
        if strong:
            updates["specialist_model"] = strong
    explicit = base.model_fields_set
    file_defaults = {name: value for name, value in updates.items() if name not in explicit}
    return base.model_copy(update=file_defaults)


def load_settings(config_path: Path | None = None) -> tuple[Settings, SwarmFileConfig]:
    """Load ``Settings`` merged with the YAML file config."""
    file_cfg = load_swarm_config(config_path)
    return settings_from_file(file_cfg), file_cfg


__all__ = [
    "EmbeddingConfig",
    "ParallelismConfig",
    "ProviderEntry",
    "Mem0StoreConfig",
    "QdrantStoreConfig",
    "RerankConfig",
    "RouterConfig",
    "SwarmFileConfig",
    "VectorStoreConfig",
    "default_config_path",
    "load_settings",
    "load_swarm_config",
    "settings_from_file",
]
