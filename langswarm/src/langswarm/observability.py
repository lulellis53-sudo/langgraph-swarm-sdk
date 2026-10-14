"""LangSmith tracing control.

LangSmith auto-traces every LangGraph node, LLM call, and tool invocation as
soon as ``LANGSMITH_TRACING=true`` and ``LANGSMITH_API_KEY`` are present in
the environment. This module manages that configuration, reports readiness,
and provides lazy access to the LangSmith client for custom work.
"""

__lazy_modules__ = ["langsmith"]

import os

_REQUIRED_VARS = ("LANGSMITH_TRACING", "LANGSMITH_API_KEY")


def tracing_enabled() -> bool:
    """Return True when LangSmith tracing is switched on for this process."""
    return os.environ.get("LANGSMITH_TRACING", "").lower() == "true"


def tracing_ready() -> bool:
    """Return True when tracing is enabled and an API key is configured."""
    return tracing_enabled() and bool(os.environ.get("LANGSMITH_API_KEY"))


def configure_tracing(*, project: str | None = None, enabled: bool = True) -> bool:
    """Set LangSmith tracing state for the process and report readiness."""
    os.environ["LANGSMITH_TRACING"] = "true" if enabled else "false"
    if project is not None:
        os.environ["LANGSMITH_PROJECT"] = project
    return tracing_ready()


def client():
    """Lazily import and return a configured LangSmith ``Client``.

    The import happens inside the function body, so the LangSmith SDK is only
    loaded when the client is genuinely requested.
    """
    if not tracing_ready():
        missing = [var for var in _REQUIRED_VARS if not os.environ.get(var)]
        raise RuntimeError(
            f"LangSmith tracing is not configured; missing: {', '.join(missing)}"
        )
    from langsmith import Client

    return Client(default_project=os.environ.get("LANGSMITH_PROJECT", "default"))
