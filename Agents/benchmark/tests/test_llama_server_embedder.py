"""Tests for the llama-server (Vulkan) embedder and the VRAM budget helpers."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest
from swarm_sdk.config import Settings
from swarm_sdk.core.swarm import default_embedder
from swarm_sdk.gpu.vram import fits_vram, kv_cache_mib, vram_total_mib
from swarm_sdk.retrieval.embeddings import EmbeddingServerError, LlamaServerEmbedder

DIM = 8


class _Handler(BaseHTTPRequestHandler):
    """HTTP handler double that records requests and can fail or redirect."""

    seen: list[dict[str, object]] = []
    mode = "ok"
    redirect_to = ""

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(body)
        if type(self).mode == "redirect":
            self.send_response(307)
            self.send_header("Location", type(self).redirect_to)
            self.end_headers()
            return
        if self.path != "/v1/embeddings" or type(self).mode == "500":
            self.send_response(500)
            self.end_headers()
            return
        inputs = body["input"]
        dim = DIM + 1 if type(self).mode == "bad_dim" else DIM
        # Return rows out of order to prove the client sorts by ``index``.
        data = [
            {"index": i, "embedding": [float(i + 1)] + [0.0] * (dim - 1)}
            for i in range(len(inputs))
        ][::-1]
        payload = json.dumps({"data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@pytest.fixture
def server() -> Iterator[str]:
    _Handler.seen = []
    _Handler.mode = "ok"
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    thread.join(timeout=5)
    httpd.server_close()


def test_embeds_in_order_batches_and_normalizes(server: str) -> None:
    embedder = LlamaServerEmbedder(server, model="bge-m3", dim=DIM, batch_size=2)
    vectors = embedder.embed(["a", "b", "c"])
    assert vectors.shape == (3, DIM)
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert len(_Handler.seen) == 2  # 3 texts, batch_size 2
    assert _Handler.seen[0]["model"] == "bge-m3"


def test_bge_v1_models_get_query_prefix(server: str) -> None:
    embedder = LlamaServerEmbedder(server, model="bge-small-en", dim=DIM)
    embedder.embed(["hello"], query=True)
    assert _Handler.seen[0]["input"] == ["query: hello"]


def test_empty_input_makes_no_request(server: str) -> None:
    embedder = LlamaServerEmbedder(server, dim=DIM)
    assert embedder.embed([]).shape == (0, DIM)
    assert _Handler.seen == []


def test_http_error_raises_domain_error(server: str) -> None:
    _Handler.mode = "500"
    with pytest.raises(EmbeddingServerError):
        LlamaServerEmbedder(server, dim=DIM).embed(["x"])


def test_dimension_mismatch_raises(server: str) -> None:
    _Handler.mode = "bad_dim"
    with pytest.raises(EmbeddingServerError, match="dimension"):
        LlamaServerEmbedder(server, dim=DIM).embed(["x"])


def test_unreachable_server_raises_domain_error() -> None:
    embedder = LlamaServerEmbedder("http://127.0.0.1:9", dim=DIM, timeout_s=1.0)
    with pytest.raises(EmbeddingServerError):
        embedder.embed(["x"])


@pytest.mark.parametrize("url", ["https://api.example.com", "http://10.0.0.5:8080", "file:///x"])
def test_non_loopback_url_is_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        LlamaServerEmbedder(url, dim=DIM)


def test_factory_builds_llama_server_embedder() -> None:
    settings = Settings(embed_backend="llama-server", llama_server_url="http://127.0.0.1:8080")
    assert isinstance(default_embedder(settings), LlamaServerEmbedder)


def test_kv_cache_formula() -> None:
    # 2 * layers * kv_heads * head_dim * ctx * bytes, in MiB.
    assert kv_cache_mib(n_layers=28, n_kv_heads=2, d_head=128, n_ctx=4096) == pytest.approx(
        2 * 28 * 2 * 128 * 4096 * 2 / 2**20
    )


def test_vram_budget_boundary() -> None:
    assert vram_total_mib(1650, 400, 100) == 2150
    assert fits_vram(1650, 400, 100)
    assert fits_vram(3800, 0)  # exactly at the 3800 MiB budget
    assert not fits_vram(3800, 1)
    assert not fits_vram(2000, 400, budget_mib=2000)


def test_redirect_is_refused_and_target_never_contacted(server: str) -> None:
    hits: list[str] = []

    class _Target(BaseHTTPRequestHandler):
        """Redirect target that records any request it receives."""

        def do_POST(self) -> None:
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    target = HTTPServer(("127.0.0.1", 0), _Target)
    thread = threading.Thread(target=target.serve_forever, daemon=True)
    thread.start()
    try:
        _Handler.mode = "redirect"
        _Handler.redirect_to = f"http://127.0.0.1:{target.server_address[1]}/steal"
        with pytest.raises(EmbeddingServerError):
            LlamaServerEmbedder(server, dim=DIM).embed(["secret repo text"])
    finally:
        target.shutdown()
        thread.join(timeout=5)
        target.server_close()
    assert hits == []
