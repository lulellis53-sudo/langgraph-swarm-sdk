"""Langswarm: a lazy, observable, twelve-agent swarm SDK.

The package root deliberately imports nothing at load time. Public names are
resolved on first attribute access, so ``import langswarm`` is near-instant
and heavy dependencies load only when a swarm is actually built.
"""

__version__ = "0.3.0"

_EXPORTS: dict[str, tuple[str, str]] = {
    "AgentSpec": ("langswarm.agents", "AgentSpec"),
    "build_agent": ("langswarm.agents", "build_agent"),
    "SwarmSpec": ("langswarm.swarm", "SwarmSpec"),
    "build_swarm": ("langswarm.swarm", "build_swarm"),
    "SwarmBlueprint": ("langswarm.blueprint", "SwarmBlueprint"),
    "AgentBlueprint": ("langswarm.blueprint", "AgentBlueprint"),
    "load_blueprint": ("langswarm.blueprint", "load_blueprint"),
    "build_from_blueprint": ("langswarm.swarm", "build_from_blueprint"),
    "run_swarm": ("langswarm.runner", "run_swarm"),
    "stream_swarm": ("langswarm.runner", "stream_swarm"),
    "configure_tracing": ("langswarm.observability", "configure_tracing"),
    "tracing_enabled": ("langswarm.observability", "tracing_enabled"),
    "tracing_ready": ("langswarm.observability", "tracing_ready"),
    "settings": ("langswarm.config", "settings"),
    "setup_logging": ("langswarm.log", "setup_logging"),
    "install_uvloop": ("langswarm.runtime", "install_uvloop"),
    "setup_telemetry": ("langswarm.telemetry", "setup_telemetry"),
    "FastEmbeddings": ("langswarm.embeddings", "FastEmbeddings"),
    "build_vectorstore": ("langswarm.retrieval", "build_vectorstore"),
    "json_dumps": ("langswarm.codec", "json_dumps"),
    "json_loads": ("langswarm.codec", "json_loads"),
    "resolve_tools": ("langswarm.tools", "resolve_tools"),
    "create_app": ("langswarm.api", "create_app"),
}
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attr = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module 'langswarm' has no attribute {name!r}") from None
    from importlib import import_module

    return getattr(import_module(module_name), attr)
