"""Token cache-hit benchmark task: repeated prompts hit the semantic cache."""

import pytest
from benchmark.metrics import Timer


@pytest.mark.asyncio
async def test_token_cache_hit(bench_sdk) -> None:
    with Timer() as timer:
        first = await bench_sdk.run("Hello bench", "t1")
        second = await bench_sdk.run("hello bench", "t2")
    assert first.cached is False
    assert second.cached is True
    assert second.tokens == 0
    assert timer.elapsed_ms >= 0
