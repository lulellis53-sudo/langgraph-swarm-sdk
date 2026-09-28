"""Execution domain: event-loop offloading and parallel fan-out."""

from swarm_sdk.execution.executor import install_uvloop, offload
from swarm_sdk.execution.fanout import HandoffPayload, SpecialistResult, fan_out

__all__ = [
    "HandoffPayload",
    "SpecialistResult",
    "fan_out",
    "install_uvloop",
    "offload",
]
