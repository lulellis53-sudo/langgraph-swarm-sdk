"""Lost-in-the-middle mitigation: place the strongest passages at both ends of a prompt."""

from __future__ import annotations

from collections.abc import Sequence


def u_shape[T](items: Sequence[T]) -> list[T]:
    """Reorder best-first ``items`` so rank 1 is first and rank 2 is last.

    Ranks alternate between the front and the back, which leaves the weakest
    items in the middle, where decoder-only models attend least. The result is
    always a permutation of the input.
    """
    front: list[T] = []
    back: list[T] = []
    for index, item in enumerate(items):
        (front if index % 2 == 0 else back).append(item)
    return front + back[::-1]


def order_for_prompt[T](items: Sequence[T], *, enabled: bool) -> list[T]:
    """Return ``items`` unchanged, or U-shaped when ``enabled``."""
    return u_shape(items) if enabled else list(items)


__all__ = ["order_for_prompt", "u_shape"]
