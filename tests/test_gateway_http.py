"""HTTP behaviour of the model gateway router."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import ConfigDict

from swarm_sdk.serving.gateway import build_router

TOKEN = "t0k"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BODY = {"model": "fake:a", "messages": [{"role": "user", "content": "hi"}]}


class StreamFake(BaseChatModel):
    """Streams ``chunks``; raises ``RuntimeError`` when the index reaches ``error_at``."""

    chunks: list[AIMessageChunk]
    error_at: int | None = None
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "stream-fake"

    def bind_tools(self, tools: object, **kwargs: object) -> StreamFake:
        del tools, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        if self.error_at == 0:
            raise RuntimeError("boom")
        merged = self.chunks[0]
        for chunk in self.chunks[1:]:
            merged = merged + chunk
        message = AIMessage(
            content=merged.content,
            tool_calls=merged.tool_calls,
            usage_metadata=merged.usage_metadata,
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        del messages, stop, run_manager, kwargs
        for index, chunk in enumerate(self.chunks):
            if self.error_at is not None and index >= self.error_at:
                raise RuntimeError("boom")
            yield ChatGenerationChunk(message=chunk)
        if self.error_at is not None and self.error_at >= len(self.chunks):
            raise RuntimeError("boom")


def make_client(models: dict[str, StreamFake], token: str | None = TOKEN) -> TestClient:
    router = build_router(
        token=lambda: token,
        loader=lambda name: models[name],
        routes=lambda: tuple(models),
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def text_model(text: str = "hello") -> StreamFake:
    return StreamFake(chunks=[AIMessageChunk(content=text)])


def test_missing_token_is_401() -> None:
    client = make_client({"fake:a": text_model()})
    assert client.post("/v1/chat/completions", json=BODY).status_code == 401


def test_wrong_token_is_401() -> None:
    client = make_client({"fake:a": text_model()})
    response = client.post(
        "/v1/chat/completions", json=BODY, headers={"Authorization": "Bearer nope"}
    )
    assert response.status_code == 401


def test_unconfigured_token_fails_closed_with_503() -> None:
    client = make_client({"fake:a": text_model()}, token=None)
    assert client.post("/v1/chat/completions", json=BODY, headers=AUTH).status_code == 503


def test_unauthenticated_malformed_body_is_401_not_422() -> None:
    client = make_client({"fake:a": text_model()})
    assert client.post("/v1/chat/completions", json={"nope": 1}).status_code == 401


def test_models_lists_routes() -> None:
    client = make_client({"fake:a": text_model(), "fake:b": text_model()})
    response = client.get("/v1/models", headers=AUTH)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == ["fake:a", "fake:b"]


def test_unknown_route_is_404() -> None:
    client = make_client({"fake:a": text_model()})
    body = {**BODY, "model": "fake:missing"}
    assert client.post("/v1/chat/completions", json=body, headers=AUTH).status_code == 404


def test_bad_role_is_422() -> None:
    client = make_client({"fake:a": text_model()})
    body = {**BODY, "messages": [{"role": "narrator", "content": "x"}]}
    assert client.post("/v1/chat/completions", json=body, headers=AUTH).status_code == 422


def test_non_streaming_text_completion() -> None:
    client = make_client({"fake:a": text_model("hello")})
    response = client.post("/v1/chat/completions", json=BODY, headers=AUTH)
    assert response.status_code == 200
    choice = response.json()["choices"][0]
    assert choice["message"] == {"role": "assistant", "content": "hello"}
    assert choice["finish_reason"] == "stop"


def test_non_streaming_tool_call() -> None:
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": "ls", "args": '{"path": "."}', "id": "call_1", "index": 0}],
    )
    client = make_client({"fake:a": StreamFake(chunks=[chunk])})
    body = {**BODY, "tools": [{"type": "function", "function": {"name": "ls", "parameters": {}}}]}
    choice = client.post("/v1/chat/completions", json=body, headers=AUTH).json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "ls"
