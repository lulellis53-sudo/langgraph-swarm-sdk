"""Cross-encoder rerankers. Only the top documents are injected into the prompt."""

from __future__ import annotations

import importlib
from collections.abc import Iterable
from typing import Protocol, cast

from swarm_sdk.math import bm25_keyword_rerank_score, keyword_overlap_score


class Reranker(Protocol):
    def rerank(self, query: str, documents: list[str]) -> list[str]: ...


class IdentityReranker:
    def rerank(self, query: str, documents: list[str]) -> list[str]:
        del query
        return list(documents)


class KeywordReranker:
    """Lexical stand-in used when the ONNX cross-encoder is not installed.

    Scores each document with a normalized token-set overlap so longer
    documents do not automatically outrank shorter ones.
    """

    def rerank(self, query: str, documents: list[str]) -> list[str]:
        needles = set(query.lower().split())

        def score(document: str) -> float:
            return keyword_overlap_score(needles, set(document.lower().split()))

        ranked = sorted(documents, key=score, reverse=True)
        return ranked


class Bm25KeywordReranker:
    """BM25-style lexical reranker that rewards term frequency and saturation."""

    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def rerank(self, query: str, documents: list[str]) -> list[str]:
        def score(document: str) -> float:
            return bm25_keyword_rerank_score(query, document, k1=self.k1, b=self.b)

        ranked = sorted(documents, key=score, reverse=True)
        return ranked


class FastEmbedReranker:
    def __init__(self, model_name: str = "Xenova/ms-marco-MiniLM-L-6-v2") -> None:
        self.model_name = model_name
        self._model: CrossEncoderProto | None = None

    def rerank(self, query: str, documents: list[str]) -> list[str]:
        if not documents:
            return []
        encoder = self._load()
        scores = list(encoder.rerank(query, documents))
        order = sorted(range(len(documents)), key=lambda index: scores[index], reverse=True)
        return [documents[index] for index in order]

    def _load(self) -> CrossEncoderProto:
        if self._model is None:
            try:
                module = importlib.import_module("fastembed.rerank.cross_encoder")
            except ImportError as exc:
                raise ImportError(
                    "fastembed is not installed. onnxruntime publishes no macOS x86_64 wheel."
                ) from exc
            encoder_cls = getattr(module, "TextCrossEncoder")
            self._model = cast(CrossEncoderProto, encoder_cls(model_name=self.model_name))
        return self._model


class CrossEncoderProto(Protocol):
    def rerank(self, query: str, documents: list[str]) -> Iterable[float]: ...


__all__ = [
    "Bm25KeywordReranker",
    "CrossEncoderProto",
    "FastEmbedReranker",
    "IdentityReranker",
    "KeywordReranker",
    "Reranker",
]
