"""Execution domain: event-loop offloading and parallel fan-out."""

from __future__ import annotations

from swarm_sdk.execution.concurrency import gil_enabled, parallel_cap
from swarm_sdk.execution.executor import install_uvloop, offload
from swarm_sdk.execution.fanout import HandoffPayload, SpecialistResult, fan_out

__all__ = [
    "HandoffPayload",
    "SpecialistResult",
    "fan_out",
    "gil_enabled",
    "install_uvloop",
    "offload",
    "parallel_cap",
]
