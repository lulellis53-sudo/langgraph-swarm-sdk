"""CRAG-lite confidence gate over reranker scores (Yan et al., 2024)."""

from __future__ import annotations

import enum
from collections.abc import Sequence

from pydantic import BaseModel, model_validator


class Confidence(enum.StrEnum):
    """Retrieval-gate confidence buckets."""

    HIGH = "high"
    AMBIGUOUS = "ambiguous"
    LOW = "low"


class GateConfig(BaseModel):
    """Thresholds are in the active reranker's score scale.

    ``KeywordReranker`` scores lie in [0, 1]; ``FastEmbedReranker`` returns raw
    cross-encoder logits, so calibrate ``high``/``low`` per reranker.
    """

    enabled: bool = False
    high: float = 0.5
    low: float = 0.27

    @model_validator(mode="after")
    def _ordered(self) -> GateConfig:
        if self.low > self.high:
            raise ValueError("gate.low must be <= gate.high")
        return self


def classify(scores: Sequence[float], config: GateConfig) -> Confidence:
    """Classify retrieval confidence from the best reranker score."""
    if not scores:
        return Confidence.LOW
    best = max(scores)
    if best >= config.high:
        return Confidence.HIGH
    if best < config.low:
        return Confidence.LOW
    return Confidence.AMBIGUOUS


__all__ = ["Confidence", "GateConfig", "classify"]
