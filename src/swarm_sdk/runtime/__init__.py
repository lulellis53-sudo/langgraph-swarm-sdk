"""Runtime plumbing: event-loop offloading, parallel fan-out and usage tracking.

Import ``metrics`` and ``tracing`` as submodules (``from swarm_sdk.runtime import metrics``).
"""

from swarm_sdk.runtime.concurrency import gil_enabled, parallel_cap
from swarm_sdk.runtime.executor import install_uvloop, offload
from swarm_sdk.runtime.fanout import HandoffPayload, SpecialistResult, fan_out
from swarm_sdk.runtime.usage import UsageLog

__all__ = [
    "HandoffPayload",
    "SpecialistResult",
    "UsageLog",
    "fan_out",
    "gil_enabled",
    "install_uvloop",
    "offload",
    "parallel_cap",
]
