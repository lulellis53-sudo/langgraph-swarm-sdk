"""Errors raised by the web-grounded prediction engine."""

from __future__ import annotations

__all__ = ["InsufficientEvidenceError", "PredictionError", "WebSearchToolError"]


class PredictionError(Exception):
    """Base error for the web prediction engine."""


class WebSearchToolError(PredictionError):
    """Raised when the WebSearch tool call fails."""


class InsufficientEvidenceError(PredictionError):
    """Raised when gathered evidence cannot support a forecast."""
