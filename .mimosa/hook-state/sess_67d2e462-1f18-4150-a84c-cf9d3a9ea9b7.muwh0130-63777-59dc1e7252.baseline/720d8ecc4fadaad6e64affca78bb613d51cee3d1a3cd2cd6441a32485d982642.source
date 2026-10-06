"""Token-usage rollups with Polars."""

from __future__ import annotations

# (input, output) USD per 1k tokens. Usage rows only carry a total, so the
# blended rate is the mean; unknown models cost 0.0 and never raise.
MODEL_RATES_USD_PER_1K: dict[str, tuple[float, float]] = {
    "openai:gpt-4o-mini": (0.00015, 0.0006),
    "openai:gpt-4o": (0.0025, 0.01),
}


def estimate_cost_usd(model: str, tokens: int) -> float:
    """Return an approximate USD cost for ``tokens`` on ``model`` (0.0 if unknown)."""
    rates = MODEL_RATES_USD_PER_1K.get(model)
    if rates is None:
        return 0.0
    return (tokens / 1000.0) * (rates[0] + rates[1]) / 2.0


class UsageLog:
    """Accumulate per-agent token rows and summarize with Polars."""

    def __init__(self) -> None:
        """Create an empty usage log."""
        self._rows: list[dict[str, object]] = []

    def add(
        self,
        agent: str,
        tokens: int,
        cached: bool,
        *,
        latency_ms: float = 0.0,
        model: str = "",
    ) -> None:
        """Record one usage event.

        Args:
            agent: Agent or subsystem name (e.g. ``"coder"``, ``"cache"``).
            tokens: Tokens charged to that agent for this event.
            cached: Whether the response came from the semantic cache.
            latency_ms: Wall time for the event in milliseconds.
            model: Model name used for the cost estimate (may be empty).
        """
        self._rows.append(
            {
                "agent": agent,
                "tokens": tokens,
                "cached": cached,
                "latency_ms": latency_ms,
                "cost_usd": estimate_cost_usd(model, tokens),
            }
        )

    def summary(self) -> list[dict[str, object]]:
        """Sum tokens, latency and estimated cost per agent, sorted by agent name.

        Returns:
            Rows of ``agent``, ``tokens``, ``latency_ms_total``, ``cost_estimate_usd``,
            or ``[]`` when empty.
        """
        if not self._rows:
            return []
        import polars as pl

        frame = pl.DataFrame(self._rows)
        grouped = frame.group_by("agent").agg(
            pl.col("tokens").sum().alias("tokens"),
            pl.col("latency_ms").sum().alias("latency_ms_total"),
            pl.col("cost_usd").sum().alias("cost_estimate_usd"),
        )
        return grouped.sort("agent").to_dicts()
