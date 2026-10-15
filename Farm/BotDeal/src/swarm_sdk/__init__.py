"""LangGraph swarm SDK with memory, reranking, token budgets, and semantic cache.

The public surface is exactly three names (:data:`RunResult`, :data:`Settings`,
:data:`SwarmSDK`). They are resolved **lazily** through :pep:`562` module
``__getattr__`` rather than imported here, because importing them eagerly pulls
in the whole retrieval/memory/gpu stack: a bare ``import swarm_sdk`` used to load
47 submodules plus numpy and protobuf, costing ~69 MB RSS and ~890 ms before any
work happened.

Deferring keeps that cost from being paid by callers that only need one symbol,
and keeps ``python -m swarm_sdk.cli --help`` cheap. Submodule access
(``from swarm_sdk import vault``) still works, since an unhandled attribute falls
through to the normal import machinery.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

__all__ = ["RunResult", "Settings", "SwarmSDK"]
__version__ = "0.1.0"

#: Public name -> defining submodule. Imported on first attribute access.
_LAZY: dict[str, str] = {
    "RunResult": "swarm_sdk.core.swarm",
    "SwarmSDK": "swarm_sdk.core.swarm",
    "Settings": "swarm_sdk.config.settings",
}

if TYPE_CHECKING:  # static analysers and IDEs see the real symbols
    from swarm_sdk.config.settings import Settings
    from swarm_sdk.core.swarm import RunResult, SwarmSDK


def __getattr__(name: str) -> Any:
    """Resolve a public name on first use, then cache it on the module.

    Raises:
        AttributeError: When ``name`` is neither a lazy public symbol nor an
            importable submodule. The message matches the interpreter's own
            wording so tooling and ``hasattr`` checks behave normally.
    """
    module_name = _LAZY.get(name)
    if module_name is not None:
        module = importlib.import_module(module_name)
        value = getattr(module, name)
        globals()[name] = value  # resolve once; later access is a dict hit
        return value
    # Fall through to submodule resolution (``from swarm_sdk import vault``).
    try:
        return importlib.import_module(f"{__name__}.{name}")
    except ImportError as exc:  # pragma: no cover - defensive
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


def __dir__() -> list[str]:
    """Expose the public surface plus standard module attributes."""
    return sorted({*globals(), *_LAZY, *__all__})
