"""Optional tokenization and sentence embeddings for prediction features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl
from Prediction.engine import ForecastError


@dataclass(frozen=True, slots=True)
class TextFeatureConfig:
    """Select an embedding runtime without importing ML frameworks at module load."""

    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    backend: str = "fastembed"
    batch_size: int = 32


class TextFeatureTransformer:
    """Tokenize text and produce sentence vectors using FastEmbed or Transformers.

    ``transformers`` uses SentenceTransformers' ONNX backend when ``backend='onnx'``;
    ``fastembed`` uses its ONNX Runtime CPU implementation. These are CPU runtimes on
    Intel macOS; the Radeon OpenCL utilities in this repository do not accelerate them.
    """

    def __init__(self, config: TextFeatureConfig | None = None) -> None:
        self.config = config or TextFeatureConfig()
        if self.config.backend not in {"fastembed", "transformers", "onnx"}:
            raise ForecastError("backend must be 'fastembed', 'transformers' or 'onnx'")
        if self.config.batch_size < 1:
            raise ForecastError("batch_size must be >= 1")
        self._model: Any = None
        self._tokenizer: Any = None

    def _load(self) -> None:
        if self._model is not None:
            return
        if self.config.backend == "fastembed":
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(model_name=self.config.model_name)
            except ImportError as exc:
                raise ForecastError(
                    "FastEmbed/ONNX Runtime is unavailable; on macOS x86_64 use "
                    "backend='transformers' or install in a supported environment"
                ) from exc
            return

        try:
            from sentence_transformers import SentenceTransformer
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self.config.model_name)
            kwargs: dict[str, Any] = {"device": "cpu"}
            if self.config.backend == "onnx":
                kwargs["backend"] = "onnx"
            self._model = SentenceTransformer(self.config.model_name, **kwargs)
        except ImportError as exc:
            raise ForecastError(
                "Install sentence-transformers and transformers to use this backend"
            ) from exc

    def tokenize(self, texts: list[str]) -> list[list[str]]:
        """Return tokenizer tokens for each input string."""
        self._load()
        if self._tokenizer is None:
            try:
                from transformers import AutoTokenizer

                self._tokenizer = AutoTokenizer.from_pretrained(self.config.model_name)
            except ImportError as exc:
                raise ForecastError("Install transformers to tokenize text") from exc
        return [
            self._tokenizer.convert_ids_to_tokens(self._tokenizer.encode(text)) for text in texts
        ]

    def attach(
        self,
        frame: pl.DataFrame,
        *,
        text_column: str,
        prefix: str = "text_embedding_",
    ) -> pl.DataFrame:
        """Add vectors aligned to each row's ``unique_id`` and ``ds`` keys."""
        if not isinstance(frame, pl.DataFrame):
            raise ForecastError("frame must be a Polars DataFrame")
        required = {"unique_id", "ds", text_column}
        missing = required - set(frame.columns)
        if missing:
            raise ForecastError(f"text feature input missing columns: {sorted(missing)}")
        if any(frame.get_column(column).is_null().any() for column in required):
            raise ForecastError("IDs, timestamps and text must not contain null values")
        duplicate_keys = frame.select(pl.struct(["unique_id", "ds"]).is_duplicated().any()).item()
        if duplicate_keys:
            raise ForecastError("text feature input has duplicate (unique_id, ds) keys")
        vectors = self.transform(frame.get_column(text_column).to_list())
        features = [
            pl.Series(f"{prefix}{index}", vectors[:, index], dtype=pl.Float32)
            for index in range(vectors.shape[1])
        ]
        return frame.with_columns(features)

    def transform(self, texts: list[str]) -> np.ndarray:
        """Encode a batch of sentences into a dense float32 feature matrix."""
        if any(not isinstance(text, str) for text in texts):
            raise ForecastError("texts must contain only strings")
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        self._load()
        if self.config.backend == "fastembed":
            vectors = list(self._model.embed(texts, batch_size=self.config.batch_size))
        else:
            vectors = self._model.encode(
                texts,
                batch_size=self.config.batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        result = np.asarray(vectors, dtype=np.float32)
        if result.ndim != 2 or result.shape[0] != len(texts) or not np.isfinite(result).all():
            raise ForecastError("embedding backend returned invalid vectors")
        return result


__all__ = ["TextFeatureConfig", "TextFeatureTransformer"]
