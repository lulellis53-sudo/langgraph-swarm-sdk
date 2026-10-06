"""Stop a LangGraph handoff trail that loops or runs past its depth cap."""

from dataclasses import dataclass

__all__ = ["HandoffCycleError", "HandoffTrail", "advance_handoff"]


class HandoffCycleError(Exception):
    """A handoff returned to an agent already on the trail, or the depth cap was hit."""


def advance_handoff(source: str, target: str, depth: int, *, max_depth: int) -> int:
    """Accept one handoff and return its depth.

    Args:
        source: Agent handing off.
        target: Agent receiving the handoff.
        depth: Depth after this handoff, starting at 1.
        max_depth: Largest depth that may proceed.

    Returns:
        ``depth`` when the handoff may run.

    Raises:
        ValueError: When an agent name is blank or ``max_depth`` is below 1.
        HandoffCycleError: When an agent hands off to itself or ``depth`` is past the cap.
    """
    if not source.strip() or not target.strip():
        raise ValueError("handoff agents must be named")
    if max_depth < 1:
        raise ValueError("max_depth must be at least 1")
    if source == target:
        raise HandoffCycleError(f"{source} handed off to itself")
    if depth > max_depth:
        raise HandoffCycleError(f"handoff depth {depth} exceeds {max_depth}")
    return depth


@dataclass(frozen=True, slots=True)
class HandoffTrail:
    """Agents visited by successive handoffs.

    Attributes:
        active_agent: Agent that currently owns the turn.
        depth: How many handoffs have completed.
        max_depth: Cap shared with :func:`advance_handoff`.
        visited: Agents already entered, including the active one.
    """

    active_agent: str
    depth: int = 0
    max_depth: int = 3
    visited: tuple[str, ...] = ()

    def handoff(self, target: str) -> HandoffTrail:
        """Move from the active agent to ``target``.

        Raises:
            HandoffCycleError: When ``target`` is already on the trail or the cap is hit.
        """
        if target in self.visited:
            raise HandoffCycleError(f"cyclic handoff {self.active_agent} -> {target}")
        depth = advance_handoff(
            self.active_agent,
            target,
            self.depth + 1,
            max_depth=self.max_depth,
        )
        return HandoffTrail(
            active_agent=target,
            depth=depth,
            max_depth=self.max_depth,
            visited=(*self.visited, target),
        )
