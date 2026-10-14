"""Local text embeddings with fastembed and onnxruntime.

fastembed executes quantized ONNX models on CPU. On x86 processors that
support AVX-512 VNNI (Ice Lake Xeon and newer), onnxruntime's
CPUExecutionProvider issues VNNI instructions automatically — no special
build or flag is required, and the benefit is largest for INT8 models.
"""


class FastEmbeddings:
    """LangChain-compatible ``Embeddings`` backed by a fastembed model.

    Duck-typed on purpose: vector stores only call ``embed_query`` and
    ``embed_documents``, so importing langchain_core here is unnecessary.
    The fastembed import happens in ``__init__``, so merely importing this
    module loads neither onnxruntime nor any model weights.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        providers: list[str] | None = None,
    ) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(
            model_name=model_name,
            providers=providers or ["CPUExecutionProvider"],
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(self._model.embed([text])).tolist()
