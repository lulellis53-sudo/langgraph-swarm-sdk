"""Behavioral checks for bounded async execution."""

from __future__ import annotations

import pytest

from swarm_sdk.models.selection import bounded_gather


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1])
async def test_bounded_gather_rejects_nonpositive_concurrency(limit: int) -> None:
    async def task() -> int:
        return 1

    with pytest.raises(ValueError, match="max_concurrency must be >= 1"):
        await bounded_gather([task], max_concurrency=limit)
